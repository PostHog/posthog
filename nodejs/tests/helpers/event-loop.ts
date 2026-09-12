import { Counter, register } from 'prom-client'

interface EventLoopObserver {
    /** Stops observing and returns how many macrotasks ran since the start. */
    stop: () => number
}

/**
 * Counts the macrotasks the event loop ran while the caller was busy. Code that
 * blocks the loop from end to end leaves the count at zero, so this is a stable
 * stand-in for measuring wall-clock delay between timer ticks.
 */
export function startEventLoopObserver(): EventLoopObserver {
    let ticks = 0
    let timer: NodeJS.Timeout

    const tick = (): void => {
        ticks++
        timer = setTimeout(tick, 0)
    }

    timer = setTimeout(tick, 0)

    return {
        stop: () => {
            clearTimeout(timer)
            return ticks
        },
    }
}

/** Reads how many `yieldEventLoopIfNeeded` calls a caller made, split by whether they yielded. */
export async function getEventLoopYieldCount(caller: string, waited: 'true' | 'false'): Promise<number> {
    const metric = register.getSingleMetric('event_loop_yield_total') as Counter | undefined
    if (!metric) {
        return 0
    }
    const data = await metric.get()
    const sample = data.values.find((v) => v.labels.caller === caller && v.labels.waited === waited)
    return sample?.value ?? 0
}
