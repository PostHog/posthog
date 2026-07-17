/**
 * A one-shot wake-up that can be re-armed. `next()` loops await `wait()` to
 * park until something interesting happens; `feed()` calls `resolve()` to wake
 * a parked loop. After observing a wake-up the loop calls `reset()` to arm a
 * fresh promise for the next park.
 *
 * Used by pipeline stages that park awaiting in-flight work but must also react
 * to a concurrent feed() delivering new input (see ConcurrentlyGroupingChunkPipeline
 * and FilterMapChunkPipeline).
 */
export class ResettableSignal {
    private promise!: Promise<void>
    private resolveFn!: () => void

    constructor() {
        this.reset()
    }

    /** Park until the next resolve(). Capture the returned promise to race it. */
    public wait(): Promise<void> {
        return this.promise
    }

    public resolve(): void {
        this.resolveFn()
    }

    public reset(): void {
        this.promise = new Promise<void>((resolve) => {
            this.resolveFn = resolve
        })
    }
}
