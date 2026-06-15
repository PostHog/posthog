/**
 * A one-shot wake-up that can be re-armed. `next()` loops await `promise` to
 * park until something interesting happens; `feed()` calls `resolve()` to wake
 * a parked loop. After observing a wake-up the loop calls `reset()` to arm a
 * fresh promise for the next park.
 *
 * Used by pipeline stages that park awaiting in-flight work but must also react
 * to a concurrent feed() delivering new input (see ConcurrentlyGroupingBatchPipeline
 * and FilterMapBatchPipeline).
 */
export interface ResettableSignal {
    readonly promise: Promise<void>
    resolve: () => void
    reset: () => void
}

export function resettableSignal(): ResettableSignal {
    let resolveFn!: () => void
    let promise!: Promise<void>

    const arm = (): void => {
        promise = new Promise<void>((resolve) => {
            resolveFn = resolve
        })
    }

    arm()

    return {
        get promise(): Promise<void> {
            return promise
        },
        resolve: (): void => resolveFn(),
        reset: arm,
    }
}
