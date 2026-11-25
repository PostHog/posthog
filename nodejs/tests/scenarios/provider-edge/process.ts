import { ChildProcess, fork } from 'child_process'
import { pathToFileURL } from 'url'

import { FaultRule } from './faults'
import { FaultHold, ProviderEdge, ProviderEdgeOptions, startProviderEdge } from './index'

export type EdgeProcessOptions = Omit<ProviderEdgeOptions, 'truth'>

export type EdgeProcess = Pick<ProviderEdge, 'url' | 'caCertPath'> & {
    hold(rule: FaultRule): Promise<FaultHold>
    clearFaults(): Promise<void>
    close(): Promise<void>
}

type Request =
    | { id: number; op: 'hold'; rule: FaultRule }
    | { id: number; op: 'observed'; hold: number; ended: boolean }
    | { id: number; op: 'end'; hold: number }
    | { id: number; op: 'release'; hold: number }
    | { id: number; op: 'clear' }

type Started = { kind: 'started'; url: string; caCertPath?: string }

type Message =
    | Started
    | { kind: 'failed'; reason: string }
    | { kind: 'reply'; id: number; value?: unknown; reason?: string }

type Pending = { resolve(value: unknown): void; reject(error: Error): void }

type Held = { held: FaultHold; ends: AbortController }

const TSX = pathToFileURL(require.resolve('tsx')).href

async function serveEdge(options: EdgeProcessOptions): Promise<void> {
    const edge = await startProviderEdge(options)
    const holds = new Map<number, Held>()
    const heldBy = (hold: number): Held => {
        const held = holds.get(hold)
        if (!held) {
            throw new Error(`the provider edge holds no fault ${hold}`)
        }
        return held
    }

    const answer = async (request: Request): Promise<unknown> => {
        switch (request.op) {
            case 'hold':
                holds.set(request.id, { held: edge.hold(request.rule), ends: new AbortController() })
                return request.id
            case 'observed': {
                const { held, ends } = heldBy(request.hold)
                if (request.ended) {
                    ends.abort()
                }
                return held.observed(ends.signal)
            }
            case 'end':
                heldBy(request.hold).ends.abort()
                return
            case 'release': {
                const { held, ends } = heldBy(request.hold)
                ends.abort()
                holds.delete(request.hold)
                return held.release()
            }
            case 'clear':
                edge.clearFaults()
                return
        }
    }

    process.on('message', (request: Request) => {
        answer(request).then(
            (value) => process.send!({ kind: 'reply', id: request.id, value } satisfies Message),
            (error: unknown) =>
                process.send!({ kind: 'reply', id: request.id, reason: String(error) } satisfies Message)
        )
    })
    process.send!({ kind: 'started', url: edge.url, caCertPath: edge.caCertPath } satisfies Message)
}

export async function startEdgeProcess(options: EdgeProcessOptions): Promise<EdgeProcess> {
    const child: ChildProcess = fork(__filename, [], {
        execArgv: ['--import', TSX],
        stdio: ['ignore', 'ignore', 'inherit', 'ipc'],
    })
    child.unref()
    child.channel?.unref()
    const pending = new Map<number, Pending>()
    let starting: Pending | undefined
    let ended: Error | undefined
    let next = 0

    const end = (error: Error): void => {
        ended ??= error
        starting?.reject(error)
        pending.forEach(({ reject }) => reject(error))
        pending.clear()
    }
    const exited = new Promise<void>((resolve) =>
        child.once('exit', (code, signal) => {
            end(new Error(`the provider edge process exited with ${signal ?? code}`))
            resolve()
        })
    )
    child.on('error', (error) => end(new Error(`the provider edge process failed: ${error.message}`)))

    const started = new Promise<Started>((resolve, reject) => {
        starting = { resolve: resolve as Pending['resolve'], reject }
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
    child.send({ options })

    const call = <T>(request: Omit<Request, 'id'>): Promise<T> => {
        if (ended) {
            return Promise.reject(ended)
        }
        const id = next++
        return new Promise<T>((resolve, reject) => {
            pending.set(id, { resolve: resolve as Pending['resolve'], reject })
            child.send({ ...request, id } as Request)
        })
    }

    const close = async (): Promise<void> => {
        child.kill('SIGKILL')
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
            const hold = await call<number>({ op: 'hold', rule })
            return {
                observed: async (holdEnds) => {
                    const ending = (): void => void call({ op: 'end', hold }).catch(() => undefined)
                    holdEnds?.addEventListener('abort', ending, { once: true })
                    try {
                        return await call<boolean>({ op: 'observed', hold, ended: holdEnds?.aborted ?? false })
                    } finally {
                        holdEnds?.removeEventListener('abort', ending)
                    }
                },
                release: () => call<void>({ op: 'release', hold }),
            }
        },
        clearFaults: () => call<void>({ op: 'clear' }),
        close,
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
