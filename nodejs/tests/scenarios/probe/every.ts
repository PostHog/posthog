import { setTimeout as sleep } from 'timers/promises'

export type Sampling<T> = { stop(): Promise<T[]> }

export function sampleEvery<T>(intervalMs: number, take: () => Promise<T>): Sampling<T> {
    const taken: T[] = []
    const stopped = new AbortController()
    const sampling = (async () => {
        while (!stopped.signal.aborted) {
            const due = Date.now() + intervalMs
            taken.push(await take())
            await sleep(Math.max(due - Date.now(), 0), undefined, { signal: stopped.signal }).catch(() => undefined)
        }
    })()
    let stopping: Promise<T[]> | undefined
    return {
        stop: () =>
            (stopping ??= (async () => {
                stopped.abort()
                await sampling
                return taken
            })()),
    }
}
