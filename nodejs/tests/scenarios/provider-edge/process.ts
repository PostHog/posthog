import { ChildProcess, fork } from 'child_process'
import { pathToFileURL } from 'url'

import { FaultRule } from './faults'
import { FaultHold, ProviderEdge, ProviderEdgeOptions, holdOf, startProviderEdge } from './index'

export type EdgeProcessOptions = Pick<ProviderEdgeOptions, 'port' | 'trackingKeys' | 'caDir' | 'feedbackUrl'>

export type EdgeProcess = Pick<ProviderEdge, 'url' | 'caCertPath'> & {
    hold(rule: FaultRule): Promise<FaultHold>
    clearFaults(): Promise<void>
    close(): Promise<void>
    readonly pid: number | undefined
}

type Call =
    | { op: 'add'; rule: FaultRule }
    | { op: 'applied'; faultId: string }
    | { op: 'hits'; faultId: string }
    | { op: 'remove'; faultId: string }
    | { op: 'clear' }

type Request = Call & { id: number }

type Started = { kind: 'started'; url: string; caCertPath?: string }

type Message =
    | Started
    | { kind: 'failed'; reason: string }
    | { kind: 'reply'; id: number; value?: unknown; reason?: string }

export type EdgeDeadlines = { startsWithinMs?: number; answersWithinMs?: number }

type Pending = { resolve(value: unknown): void; reject(error: Error): void }

type Waiting = Pending & { deadline: NodeJS.Timeout }

const TSX = pathToFileURL(require.resolve('tsx')).href
const EDGE_STARTS_WITHIN_MS = 60_000
const EDGE_ANSWERS_WITHIN_MS = 30_000

async function serveEdge(options: EdgeProcessOptions): Promise<void> {
    const edge = await startProviderEdge(options)
    const answer = (call: Call): unknown => {
        switch (call.op) {
            case 'add':
                return edge.addFault(call.rule)
            case 'applied':
                return edge.firstAppliedAt(call.faultId)
            case 'hits':
                return edge.hitsOf(call.faultId)
            case 'remove':
                return edge.removeFault(call.faultId)
            case 'clear':
                return edge.clearFaults()
        }
    }
    process.on('message', (request: Request) => {
        try {
            process.send!({ kind: 'reply', id: request.id, value: answer(request) } satisfies Message)
        } catch (error) {
            process.send!({ kind: 'reply', id: request.id, reason: String(error) } satisfies Message)
        }
    })
    process.send!({ kind: 'started', url: edge.url, caCertPath: edge.caCertPath } satisfies Message)
}

export async function startEdgeProcess(
    options: EdgeProcessOptions,
    { startsWithinMs = EDGE_STARTS_WITHIN_MS, answersWithinMs = EDGE_ANSWERS_WITHIN_MS }: EdgeDeadlines = {}
): Promise<EdgeProcess> {
    const child: ChildProcess = fork(__filename, [], {
        execArgv: ['--import', TSX],
        detached: true,
        stdio: ['ignore', 'ignore', 'inherit', 'ipc'],
    })
    const pending = new Map<number, Waiting>()
    let starting: Waiting | undefined
    let ended: Error | undefined
    let next = 0

    const end = (error: Error): void => {
        const reason = (ended ??= error)
        for (const waiting of [starting, ...pending.values()]) {
            clearTimeout(waiting?.deadline)
            waiting?.reject(reason)
        }
        starting = undefined
        pending.clear()
    }
    const kill = (): void => {
        if (child.pid !== undefined && child.exitCode === null && child.signalCode === null) {
            try {
                process.kill(-child.pid, 'SIGKILL')
            } catch (error) {
                // The group can already be gone if the child was reaped between the checks above and this signal.
                if ((error as NodeJS.ErrnoException).code !== 'ESRCH') {
                    throw error
                }
            }
        }
    }
    const readQueuedRepliesThen = (next: () => void): void => void setImmediate(next)
    const waitFor = (what: string, withinMs: number, settle: Pending, stillWaiting: () => boolean): Waiting => ({
        ...settle,
        deadline: setTimeout(
            () =>
                readQueuedRepliesThen(() => {
                    if (stillWaiting()) {
                        ended ??= new Error(`the provider edge process did not ${what} within ${withinMs} ms`)
                        try {
                            kill()
                        } catch (error) {
                            // A process that was not killed sends no exit, so reject the waiting calls here.
                            end((ended = new Error(`${ended.message}, and could not be killed`, { cause: error })))
                        }
                    }
                }),
            withinMs
        ),
    })
    const answer = (waiting: Waiting | undefined, settle: (waiting: Waiting) => void): void => {
        if (waiting !== undefined && !ended) {
            clearTimeout(waiting.deadline)
            settle(waiting)
        }
    }
    const exited = new Promise<void>((resolve) => {
        child.once('exit', (code, signal) => {
            end(new Error(`the provider edge process exited with ${signal ?? code}`))
            resolve()
        })
        child.on('error', (error) => {
            end(new Error(`the provider edge process failed: ${error.message}`, { cause: error }))
            if (child.pid === undefined) {
                resolve()
            }
        })
    })

    const started = new Promise<Started>((resolve, reject) => {
        starting = waitFor(
            'start',
            startsWithinMs,
            { resolve: resolve as Pending['resolve'], reject },
            () => starting !== undefined
        )
    })
    child.on('message', (message: Message) => {
        if (message.kind === 'reply') {
            answer(pending.get(message.id), ({ resolve, reject }) => {
                pending.delete(message.id)
                if (message.reason === undefined) {
                    resolve(message.value)
                } else {
                    reject(new Error(message.reason))
                }
            })
        } else {
            answer(starting, ({ resolve, reject }) => {
                starting = undefined
                if (message.kind === 'started') {
                    resolve(message)
                } else {
                    reject(new Error(message.reason))
                }
            })
        }
    })
    if (child.connected) {
        try {
            child.send({ options })
        } catch (error) {
            end(error as Error)
        }
    }

    const call = <T>(request: Call): Promise<T> => {
        if (ended) {
            return Promise.reject(ended)
        }
        const id = next++
        return new Promise<T>((resolve, reject) => {
            const waiting = waitFor(
                `answer ${request.op}`,
                answersWithinMs,
                { resolve: resolve as Pending['resolve'], reject },
                () => pending.has(id)
            )
            pending.set(id, waiting)
            try {
                child.send({ ...request, id } satisfies Request)
            } catch (error) {
                clearTimeout(waiting.deadline)
                pending.delete(id)
                reject(error as Error)
            }
        })
    }

    const close = async (): Promise<void> => {
        kill()
        await exited
    }

    const { url, caCertPath } = await started.catch(async (error: unknown) => {
        await close()
        throw error
    })

    return {
        url,
        caCertPath,
        hold: async (rule) => {
            const faultId = await call<string>({ op: 'add', rule })
            return holdOf({
                firstAppliedAt: () => call<number | undefined>({ op: 'applied', faultId }),
                hits: () => call<string[]>({ op: 'hits', faultId }),
                remove: () => call<void>({ op: 'remove', faultId }),
            })
        },
        clearFaults: () => call<void>({ op: 'clear' }),
        close,
        pid: child.pid,
    }
}

if (require.main === module && process.send) {
    process.once('message', ({ options }: { options: EdgeProcessOptions }) =>
        serveEdge(options).catch((error: unknown) =>
            process.send!({ kind: 'failed', reason: String(error) } satisfies Message, () => process.exit(1))
        )
    )
    process.on('disconnect', () => process.exit(0))
}
