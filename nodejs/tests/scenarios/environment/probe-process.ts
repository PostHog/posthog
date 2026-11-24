import { fork } from 'child_process'
import { pathToFileURL } from 'url'

import { parseJSON } from '~/common/utils/json-parse'

import { ProbeFailure, dependencyProbes, failedProbes } from './stack'

export type ProbeTarget = {
    edgeUrl: string | undefined
    postgresUrl: string
    sesValkey: { host: string; port: number }
    only?: string[]
}

export type ProbeProcess = { check(): Promise<ProbeFailure[]>; close(): void }

type Request = { id: number }
type Reply = { id: number; failures: ProbeFailure[] }

function serveProbes(target: ProbeTarget): void {
    const all = dependencyProbes(target.edgeUrl, target.postgresUrl, target.sesValkey)
    const only = target.only
    const probes = only ? Object.fromEntries(Object.entries(all).filter(([name]) => only.includes(name))) : all
    process.on('message', ({ id }: Request) => {
        void failedProbes(probes).then((failures) => process.send!({ id, failures } satisfies Reply))
    })
    process.on('disconnect', () => process.exit(0))
}

// The probes run in their own process, so a drive that saturates the runner's event loop cannot time them out.
// A thread is not enough: node-rdkafka loads once per process.
export function startProbeProcess(target: ProbeTarget): ProbeProcess {
    const child = fork(__filename, [JSON.stringify(target)], {
        execArgv: ['--import', pathToFileURL(require.resolve('tsx')).href],
        stdio: ['ignore', 'ignore', 'inherit', 'ipc'],
    })
    child.unref()
    child.channel?.unref()
    const pending = new Map<number, { resolve(failures: ProbeFailure[]): void; reject(error: Error): void }>()
    let ended: Error | undefined
    const end = (error: Error): void => {
        ended ??= error
        pending.forEach(({ reject }) => reject(ended!))
        pending.clear()
    }
    child.on('message', ({ id, failures }: Reply) => {
        pending.get(id)?.resolve(failures)
        pending.delete(id)
    })
    child.on('error', (error) => end(new Error(`the probe process failed: ${error.message}`)))
    child.on('exit', (code, signal) => end(new Error(`the probe process exited with ${signal ?? code}`)))
    let next = 0
    return {
        check: () =>
            ended
                ? Promise.reject(ended)
                : new Promise((resolve, reject) => {
                      const id = next++
                      pending.set(id, { resolve, reject })
                      child.send({ id } satisfies Request)
                  }),
        close: () => {
            end(new Error('the probe process was closed'))
            child.kill()
        },
    }
}

if (require.main === module && process.send) {
    serveProbes(parseJSON(process.argv[2]) as ProbeTarget)
}
