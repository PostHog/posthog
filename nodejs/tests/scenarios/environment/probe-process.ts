import { ChildProcess, fork } from 'child_process'
import { pathToFileURL } from 'url'

import { ProbeFailure, dependencyProbes, failedProbes } from './stack'

export type ProbeTarget = {
    edgeUrl: string | undefined
    postgresUrl: string
    sesValkey: { host: string; port: number }
    only?: string[]
}

export type ProbeProcess = { check(): Promise<ProbeFailure[]>; close(): void; readonly pid: number | undefined }

// The target reaches the child over IPC because a process's command line is readable by every user on the host.
type Setup = { target: ProbeTarget }
type Request = { id: number }
type Reply = { id: number; failures: ProbeFailure[] }
type Pending = { resolve(failures: ProbeFailure[]): void; reject(error: Error): void; deadline: NodeJS.Timeout }

// A check waits for every probe's own timeout, the socket listing at a host limit, and on its first check the
// child's start-up under tsx. A child that answers nothing in this time is stuck, and the runner would wait for it.
const PROBE_PROCESS_DEADLINE_MS = 30_000

// Resolving reads package.json, so a host out of file descriptors would fail it before the fork can report the limit.
const TSX = pathToFileURL(require.resolve('tsx')).href

function serveProbes(target: ProbeTarget): void {
    const all = dependencyProbes(target.edgeUrl, target.postgresUrl, target.sesValkey)
    const only = target.only
    const probes = only ? Object.fromEntries(Object.entries(all).filter(([name]) => only.includes(name))) : all
    process.on('message', ({ id }: Request) => {
        void failedProbes(probes).then((failures) => process.send!({ id, failures } satisfies Reply))
    })
}

// The probes run in their own process, so a drive that saturates the runner's event loop cannot time them out.
// A thread is not enough: node-rdkafka loads once per process.
export function startProbeProcess(target: ProbeTarget, deadlineMs = PROBE_PROCESS_DEADLINE_MS): ProbeProcess {
    const pending = new Map<number, Pending>()
    let child: ChildProcess | undefined
    let closed = false
    let next = 0

    // Ending a child fails its checks and kills it, so the next check starts a fresh one.
    const end = (ended: ChildProcess, error: Error): void => {
        if (child !== ended) {
            return
        }
        child = undefined
        ended.kill('SIGKILL')
        pending.forEach(({ reject, deadline }) => {
            clearTimeout(deadline)
            reject(error)
        })
        pending.clear()
    }

    const started = (): ChildProcess => {
        const forked = fork(__filename, [], {
            execArgv: ['--import', TSX],
            stdio: ['ignore', 'ignore', 'inherit', 'ipc'],
        })
        forked.unref()
        forked.channel?.unref()
        forked.on('message', ({ id, failures }: Reply) => {
            const request = pending.get(id)
            if (request) {
                clearTimeout(request.deadline)
                pending.delete(id)
                request.resolve(failures)
            }
        })
        forked.on('error', (error) =>
            end(forked, new Error(`the probe process failed: ${error.message}`, { cause: error }))
        )
        forked.on('exit', (code, signal) => end(forked, new Error(`the probe process exited with ${signal ?? code}`)))
        // A fork that the host had no file descriptor for has no channel, and its error event ends it.
        if (forked.connected) {
            forked.send({ target } satisfies Setup)
        }
        return forked
    }

    return {
        check: () => {
            if (closed) {
                return Promise.reject(new Error('the probe process was closed'))
            }
            const checking = (child ??= started())
            return new Promise((resolve, reject) => {
                const id = next++
                // Timers run before the loop reads I/O, so a runner blocked past the deadline would end a child whose
                // reply already waits on the channel. One more poll reads that reply first.
                const deadline = setTimeout(
                    () =>
                        setImmediate(() => {
                            if (pending.has(id)) {
                                end(checking, new Error(`the probe process did not answer within ${deadlineMs} ms`))
                            }
                        }),
                    deadlineMs
                )
                pending.set(id, { resolve, reject, deadline })
                if (checking.connected) {
                    checking.send({ id } satisfies Request)
                }
            })
        },
        close: () => {
            closed = true
            if (child) {
                end(child, new Error('the probe process was closed'))
            }
        },
        get pid() {
            return child?.pid
        },
    }
}

if (require.main === module && process.send) {
    process.once('message', ({ target }: Setup) => serveProbes(target))
    process.on('disconnect', () => process.exit(0))
}
