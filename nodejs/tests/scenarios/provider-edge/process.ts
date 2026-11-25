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
    | { op: 'remove'; faultId: string }
    | { op: 'clear' }

type Request = Call & { id: number }

type Started = { kind: 'started'; url: string; caCertPath?: string }

type Message =
    | Started
    | { kind: 'failed'; reason: string }
    | { kind: 'reply'; id: number; value?: unknown; reason?: string }

type Pending = { resolve(value: unknown): void; reject(error: Error): void }

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
    { startsWithinMs = EDGE_STARTS_WITHIN_MS, answersWithinMs = EDGE_ANSWERS_WITHIN_MS } = {}
): Promise<EdgeProcess> {
    const child: ChildProcess = fork(__filename, [], {
        execArgv: ['--import', TSX],
        detached: true,
        stdio: ['ignore', 'ignore', 'inherit', 'ipc'],
    })
    const pending = new Map<number, Pending>()
    let starting: Pending | undefined
    let ended: Error | undefined
    let next = 0

    const end = (error: Error): void => {
        const reason = (ended ??= error)
        starting?.reject(reason)
        pending.forEach(({ reject }) => reject(reason))
        pending.clear()
    }
    const kill = (): void => {
        try {
            process.kill(-child.pid!, 'SIGKILL')
        } catch {
            child.kill('SIGKILL')
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

    const giveUp = (what: string, withinMs: number): NodeJS.Timeout =>
        setTimeout(() => {
            ended ??= new Error(`the provider edge process did not ${what} within ${withinMs} ms`)
            kill()
        }, withinMs)
    const started = new Promise<Started>((resolve, reject) => {
        const deadline = giveUp('start', startsWithinMs)
        starting = {
            resolve: (value) => {
                clearTimeout(deadline)
                resolve(value as Started)
            },
            reject: (error) => {
                clearTimeout(deadline)
                reject(error)
            },
        }
    })
    child.on('message', (message: Message) => {
        if (message.kind === 'started') {
            starting?.resolve(message)
        } else if (message.kind === 'failed') {
            starting?.reject(new Error(message.reason))
        } else {
            const request = pending.get(message.id)
            pending.delete(message.id)
            if (message.reason === undefined) {
                request?.resolve(message.value)
            } else {
                request?.reject(new Error(message.reason))
            }
        }
    })
    if (child.connected) {
        child.send({ options })
    }

    const call = <T>(request: Call): Promise<T> => {
        if (ended) {
            return Promise.reject(ended)
        }
        const id = next++
        return new Promise<T>((resolve, reject) => {
            const deadline = giveUp(`answer ${request.op}`, answersWithinMs)
            pending.set(id, {
                resolve: (value) => {
                    clearTimeout(deadline)
                    resolve(value as T)
                },
                reject: (error) => {
                    clearTimeout(deadline)
                    reject(error)
                },
            })
            try {
                child.send({ ...request, id } satisfies Request)
            } catch (error) {
                pending.get(id)?.reject(error as Error)
                pending.delete(id)
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
