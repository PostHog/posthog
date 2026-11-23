import { randomUUID } from 'node:crypto'
import { join } from 'node:path'
import { z } from 'zod'

import type { FoldedField, ManualField } from '@posthog/sdk/stack'

import { HogError, type CapturedOutput } from '@/core/errors'
import { STACK_WORKER_ARG } from '@/core/runtime'
import type { Schema } from '@/core/schema'

import {
    EvaluationResult,
    FoldResult,
    WorkerFailure,
    WorkerReady,
    type Evaluation,
    type FoldEdit,
    type WorkerRequest,
} from './evaluation'
import type { Diff } from './service'

const OUTPUT_BYTES = 32 * 1024
const DEADLINE_MS = 30_000
const EXIT_GRACE_MS = 1_000

async function capture(reader: ReadableStreamDefaultReader<Uint8Array>): Promise<string> {
    const buffer = new Uint8Array(OUTPUT_BYTES)
    let size = 0
    let truncated = false
    for (;;) {
        const { value, done } = await reader.read()
        if (done) {
            break
        }
        const length = Math.min(value.length, OUTPUT_BYTES - size)
        buffer.set(value.subarray(0, length), size)
        size += length
        truncated ||= length < value.length
    }
    const text = new TextDecoder().decode(buffer.subarray(0, size))
    return truncated ? `${text}\n[Output shortened]\n` : text
}

export function evaluateInChild(
    folder: string,
    root: string,
    source: boolean,
    timeoutMs = DEADLINE_MS
): Promise<Evaluation> {
    return runInChild({ operation: 'check', folder, root }, EvaluationResult, source, timeoutMs)
}

export function foldInChild(
    folder: string,
    drift: Diff['drift'],
    source: boolean,
    files: { root: string; targets: string[] }
): Promise<{ applied: FoldedField[]; manual: ManualField[]; edits: FoldEdit[]; output: CapturedOutput }> {
    return runInChild(
        { operation: 'fold', folder, drift, root: files.root, files: files.targets },
        FoldResult,
        source,
        DEADLINE_MS
    ).catch((error: unknown) => {
        if (error instanceof HogError) {
            throw error
        }
        throw new HogError(
            'stack_fold_failed',
            "hog couldn't bring the changed fields into the definitions.",
            'Check the stack folder and run hog diff to review the remaining changes.'
        )
    })
}

// A worker on POSIX leads its own process group, so one signal reaches anything the definitions started.
// Windows has no process groups, so there only the worker itself is killed.
const GROUPS = process.platform !== 'win32'

function killGroup(child: { pid: number; kill: (signal: NodeJS.Signals) => void }): void {
    if (GROUPS) {
        try {
            process.kill(-child.pid, 'SIGKILL')
            return
        } catch {
            // The group is gone, so only the worker itself might be left.
        }
    }
    child.kill('SIGKILL')
}

type Request = z.input<typeof WorkerRequest> extends infer R ? (R extends unknown ? Omit<R, 'nonce'> : never) : never

async function runInChild<T extends object>(
    request: Request,
    resultSchema: Schema<T>,
    source: boolean,
    timeoutMs: number
): Promise<T & { output: CapturedOutput }> {
    const args = source ? ['--no-install', '--no-env-file', join(import.meta.dir, '../index.ts')] : []
    let receive!: (message: unknown) => void
    let sent = false
    let stop: ReturnType<typeof setTimeout> | undefined
    const reply = new Promise<unknown>((resolve) => {
        receive = resolve
    })
    // The worker gets the nonce in the request, which arrives before the definitions load, and must send it
    // back. That stops a definition that calls process.send, by accident or on purpose, from passing off its
    // own message as the result. It is no sandbox: definitions run in the worker's process and can still
    // rewrite the worker's real reply.
    const nonce = randomUUID()
    const Signed = z.object({ nonce: z.literal(nonce) })
    const child = Bun.spawn([process.execPath, ...args, STACK_WORKER_ARG], {
        cwd: source ? join(import.meta.dir, '../..') : request.folder,
        stdin: 'ignore',
        stdout: 'pipe',
        stderr: 'pipe',
        windowsHide: true,
        detached: GROUPS,
        // Definitions are pure and need no credentials. SystemRoot lets Windows load the executable.
        env: { SystemRoot: process.env.SystemRoot },
        ipc: (message: unknown, worker) => {
            if (!sent && WorkerReady.safeParse(message).success) {
                sent = true
                worker.send({ ...request, nonce })
                return
            }
            if (!sent || !Signed.safeParse(message).success || stop !== undefined) {
                return
            }
            receive(message)
            worker.disconnect()
            // A timer or socket that the folder's imports leave open, or a process they started that holds the
            // output open, would keep this waiting after the worker answered. The pause lets the worker finish
            // writing its output first.
            stop = setTimeout(() => {
                killGroup(child)
                void stdout.cancel().catch(() => {})
                void stderr.cancel().catch(() => {})
            }, EXIT_GRACE_MS)
        },
        onDisconnect: () => receive(undefined),
    })
    const stdout = child.stdout.getReader()
    const stderr = child.stderr.getReader()
    // The worker's own session doesn't get the terminal's Ctrl-C, so hog passes it on before it exits.
    const signals = ['SIGINT', 'SIGTERM', 'SIGHUP'] as const
    const forward = (signal: NodeJS.Signals): void => {
        killGroup(child)
        for (const name of signals) {
            process.removeListener(name, forward)
        }
        process.kill(process.pid, signal)
    }
    if (GROUPS) {
        for (const name of signals) {
            process.once(name, forward)
        }
    }
    const output = Promise.all([capture(stdout), capture(stderr)]).then(([stdout, stderr]) => ({ stdout, stderr }))
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
        const [code, logs, message] = await Promise.race([
            Promise.all([child.exited, output, reply]),
            new Promise<never>((_, reject) => {
                timer = setTimeout(() => {
                    reject(
                        new HogError(
                            'stack_evaluation_timeout',
                            `Reading this stack took longer than ${timeoutMs / 1000} seconds.`,
                            request.operation === 'fold'
                                ? 'Check for a loop or an unfinished task in the definitions, then run hog diff to review the remaining changes.'
                                : 'Check for a loop or an unfinished task in the definitions, then run hog check again.'
                        )
                    )
                    killGroup(child)
                    void stdout.cancel().catch(() => {})
                    void stderr.cancel().catch(() => {})
                }, timeoutMs)
            }),
        ])
        const failure = WorkerFailure.safeParse(message)
        if (failure.success) {
            const { code, message, hint } = failure.data.error
            throw new HogError(code, message, hint)
        }
        const parsed = resultSchema.safeParse(message)
        if ((code !== 0 && stop === undefined) || !parsed.success) {
            throw new HogError(
                request.operation === 'fold' ? 'stack_fold_failed' : 'stack_evaluation_failed',
                'The stack stopped before it returned its result.',
                'Check its index.ts and dependencies, then run hog check again.'
            )
        }
        return { ...parsed.data, output: logs }
    } catch (error) {
        if (error instanceof HogError) {
            throw new HogError(error.code, error.message, error.hint, error.exitCode, { output: await output })
        }
        throw error
    } finally {
        clearTimeout(timer)
        clearTimeout(stop)
        killGroup(child)
        for (const name of signals) {
            process.removeListener(name, forward)
        }
    }
}
