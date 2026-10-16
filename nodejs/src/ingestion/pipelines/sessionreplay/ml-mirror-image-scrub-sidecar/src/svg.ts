/* eslint-disable no-console -- sidecar logs to stdout */
import { type ChildProcess, fork } from 'node:child_process'

import { ImageOptOutError, UndecodableImageError } from './image-input.ts'
import { ScrubAbandonedError } from './pool.ts'
import { xmpProhibitsAiTraining } from './xmp.ts'

const READY_TIMEOUT_MS = 30_000
const RESTART_BACKOFF_BASE_MS = 500
const RESTART_BACKOFF_MAX_MS = 30_000
// Abandonment is otherwise checked only on dispatch, which never comes while every renderer is down.
const QUEUE_SWEEP_MS = 1_000

/**
 * The lane sends an SVG only as a document that starts with markup, and no raster format the scrub
 * takes starts with `<`, so markup after an optional BOM and whitespace is enough to tell.
 */
export function isSvgDocument(input: Buffer): boolean {
    let i = input[0] === 0xef && input[1] === 0xbb && input[2] === 0xbf ? 3 : 0
    while (i < input.length && (input[i] === 0x20 || input[i] === 0x09 || input[i] === 0x0a || input[i] === 0x0d)) {
        i++
    }
    return input[i] === 0x3c
}

export interface SvgRasterizer {
    rasterize(input: Buffer, signal?: AbortSignal): Promise<Buffer>
    usableProcesses(): number
    close(): Promise<void>
}

interface Job {
    id: number
    input: Buffer
    resolve: (png: Buffer) => void
    reject: (error: Error) => void
    signal?: AbortSignal
    queuedAt: number
}

interface Slot {
    child: ChildProcess
    job: { job: Job; deadline: NodeJS.Timeout } | null
    usable: boolean
    retired: boolean
}

type Reply = { ready: true } | { id: number; out: Uint8Array } | { id: number; refused: string }

/** The child script is a parameter because jest's CJS transform cannot load import.meta (see qr.ts). */
export async function startSvgRasterizer(
    size: number,
    childPath: string,
    timeoutMs: number,
    abandonAfterMs: number
): Promise<SvgRasterizer> {
    const slots: Slot[] = []
    const queue: Job[] = []
    const restartFailures: number[] = []
    let nextJobId = 0
    let closing = false

    const abandoned = (job: Job): boolean =>
        job.signal?.aborted === true || performance.now() - job.queuedAt > abandonAfterMs

    const pump = (): void => {
        for (const dead of queue.filter(abandoned)) {
            queue.splice(queue.indexOf(dead), 1)
            dead.reject(new ScrubAbandonedError(`svg job ${dead.id} was abandoned before it ran`))
        }
        for (const slot of slots) {
            if (!slot?.usable || slot.job || queue.length === 0) {
                continue
            }
            const job = queue.shift()!
            const deadline = setTimeout(() => {
                retire(
                    slots.indexOf(slot),
                    slot,
                    new UndecodableImageError('svg_timeout', `svg job ${job.id} timed out`)
                )
            }, timeoutMs)
            deadline.unref()
            slot.job = { job, deadline }
            slot.child.send({ id: job.id, input: job.input })
        }
    }

    const spawn = async (index: number): Promise<void> => {
        const child = fork(childPath, [], {
            serialization: 'advanced',
            execArgv: [],
            stdio: ['ignore', 'inherit', 'inherit', 'ipc'],
        })
        const slot: Slot = { child, job: null, usable: false, retired: false }
        slots[index] = slot
        child.on('error', (error) => console.error(`[image-scrub] svg rasterizer ${index}: ${String(error)}`))
        await new Promise<void>((ready, failed) => {
            const timer = setTimeout(() => {
                cleanup()
                failed(new Error(`svg rasterizer did not become ready within ${READY_TIMEOUT_MS}ms`))
            }, READY_TIMEOUT_MS)
            const onMessage = (msg: Reply): void => {
                if ('ready' in msg) {
                    cleanup()
                    ready()
                }
            }
            const onExit = (code: number | null): void => {
                cleanup()
                failed(new Error(`svg rasterizer exited with code ${code} before it was ready`))
            }
            const cleanup = (): void => {
                clearTimeout(timer)
                child.off('message', onMessage)
                child.off('exit', onExit)
            }
            child.on('message', onMessage)
            child.once('exit', onExit)
        }).catch((error: unknown) => {
            child.kill('SIGKILL')
            throw error
        })

        child.on('message', (msg: Reply) => {
            if ('ready' in msg || !slot.job || slot.job.job.id !== msg.id) {
                return
            }
            const { job, deadline } = slot.job
            clearTimeout(deadline)
            slot.job = null
            restartFailures[index] = 0
            if ('refused' in msg) {
                job.reject(new UndecodableImageError('svg_refused', msg.refused))
            } else {
                job.resolve(Buffer.from(msg.out.buffer, msg.out.byteOffset, msg.out.byteLength))
            }
            pump()
        })
        child.on('exit', (code, signal) =>
            retire(index, slot, new Error(`svg rasterizer exited with ${signal ?? `code ${code}`}`))
        )
        slot.usable = true
    }

    const retire = (index: number, slot: Slot, error: Error): void => {
        if (closing || slot.retired) {
            return
        }
        slot.retired = true
        slot.usable = false
        if (slot.job) {
            clearTimeout(slot.job.deadline)
            slot.job.job.reject(error)
            slot.job = null
        }
        slot.child.kill('SIGKILL')
        scheduleReplacement(index)
    }

    const scheduleReplacement = (index: number): void => {
        const failures = (restartFailures[index] ?? 0) + 1
        restartFailures[index] = failures
        const delayMs =
            failures === 1 ? 0 : Math.min(RESTART_BACKOFF_MAX_MS, RESTART_BACKOFF_BASE_MS * 2 ** (failures - 2))
        const timer = setTimeout(() => {
            if (closing) {
                return
            }
            spawn(index)
                .then(pump)
                .catch((error: unknown) => {
                    console.error(`[image-scrub] svg rasterizer ${index} failed to restart: ${String(error)}`)
                    scheduleReplacement(index)
                })
        }, delayMs)
        timer.unref()
    }

    await Promise.all(Array.from({ length: size }, (_unused, i) => spawn(i)))
    const sweep = setInterval(pump, QUEUE_SWEEP_MS)
    sweep.unref()

    return {
        rasterize(input: Buffer, signal?: AbortSignal): Promise<Buffer> {
            if (closing) {
                return Promise.reject(new Error('svg rasterizer is closing'))
            }
            // Rendering drops the document's metadata, so its training opt-out is read first.
            let optedOut: boolean
            try {
                optedOut = xmpProhibitsAiTraining(input)
            } catch {
                return Promise.reject(new UndecodableImageError('svg_refused', 'svg is not well-formed XML'))
            }
            if (optedOut) {
                return Promise.reject(new ImageOptOutError('image metadata prohibits AI training'))
            }
            return new Promise<Buffer>((resolve, reject) => {
                queue.push({ id: nextJobId++, input, resolve, reject, signal, queuedAt: performance.now() })
                pump()
            })
        },
        usableProcesses(): number {
            return slots.filter((s) => s?.usable).length
        },
        async close(): Promise<void> {
            closing = true
            clearInterval(sweep)
            for (const job of queue.splice(0)) {
                job.reject(new Error('svg rasterizer is closing'))
            }
            await Promise.all(
                slots.filter(Boolean).map(
                    (slot) =>
                        new Promise<void>((done) => {
                            if (slot.job) {
                                clearTimeout(slot.job.deadline)
                                slot.job.job.reject(new Error('svg rasterizer is closing'))
                            }
                            if (slot.child.exitCode !== null || slot.child.signalCode !== null) {
                                done()
                                return
                            }
                            slot.child.once('exit', () => done())
                            slot.child.kill('SIGKILL')
                        })
                )
            )
        },
    }
}
