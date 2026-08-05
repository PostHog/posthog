import { Counter, Histogram } from 'prom-client'

const DEFAULT_THRESHOLD_MS = 200

let defaultThresholdMs = DEFAULT_THRESHOLD_MS

let state: {
    startedAt: number
    promise: Promise<void>
} | null = null

const eventLoopYieldCounter = new Counter({
    name: 'event_loop_yield_total',
    help: 'Total calls to yieldEventLoopIfNeeded, labelled by caller and whether the call actually yielded',
    labelNames: ['caller', 'waited'],
})

const eventLoopYieldBlockedMs = new Histogram({
    name: 'event_loop_yield_blocked_duration_ms',
    help: 'How long the event loop went without yielding before yieldEventLoopIfNeeded forced a yield',
    labelNames: ['caller'],
    buckets: [50, 100, 200, 500, 1000, 2500, 5000, 10000],
})

const eventLoopYieldWaitMs = new Histogram({
    name: 'event_loop_yield_wait_duration_ms',
    help: 'How long the await for setTimeout(0) actually took to resolve once yieldEventLoopIfNeeded forced a yield',
    labelNames: ['caller'],
    buckets: [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500],
})

export function configureEventLoopYield(thresholdMs: number): void {
    defaultThresholdMs = thresholdMs
}

export function getEventLoopYieldThresholdMs(): number {
    return defaultThresholdMs
}

async function yieldIfNeeded(caller: string): Promise<void> {
    if (!state) {
        state = {
            startedAt: performance.now(),
            promise: new Promise((resolve) => {
                setTimeout(() => {
                    state = null
                    resolve()
                }, 0)
            }),
        }
    }

    const blockedFor = performance.now() - state.startedAt
    if (blockedFor < defaultThresholdMs) {
        eventLoopYieldCounter.inc({ caller, waited: 'false' })
        return
    }

    eventLoopYieldBlockedMs.observe({ caller }, blockedFor)

    const awaitStartedAt = performance.now()
    await state.promise
    eventLoopYieldWaitMs.observe({ caller }, performance.now() - awaitStartedAt)
    eventLoopYieldCounter.inc({ caller, waited: 'true' })
}

/**
 * Run `fn` with event-loop protection: yields before `fn` to ensure any
 * accumulated sync work from earlier callers is accounted for, and yields
 * after `fn` (regardless of whether it resolved or threw). The before-yield
 * also primes the shared state so `fn`'s own runtime accumulates into it.
 */
export async function yieldEventLoopIfNeeded<T>(caller: string, fn: () => T | Promise<T>): Promise<T> {
    await yieldIfNeeded(caller)
    try {
        return await fn()
    } finally {
        await yieldIfNeeded(caller)
    }
}

/**
 * Iterate `items`, calling `fn(item, index)` for each, with a yield between
 * iterations. Use this anywhere you'd write a `for ... of` over a CPU-bound batch.
 */
export async function yieldEach<T>(
    caller: string,
    items: ArrayLike<T>,
    fn: (item: T, index: number) => void | Promise<void>
): Promise<void> {
    if (items.length === 0) {
        return
    }
    await yieldIfNeeded(caller)
    for (let i = 0; i < items.length; i++) {
        try {
            await fn(items[i], i)
        } finally {
            await yieldIfNeeded(caller)
        }
    }
}
