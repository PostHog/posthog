import pLimit from 'p-limit'

import { SessionRecordingIngesterMetrics } from './metrics'

type Timed<T> = { value: T; finishedAt: number }

/** Open while the admitting tick runs; every stage of a batch must be queued before it closes, or a later batch could enter a stage first. */
type Admission = { sequence: number; open: boolean }

/**
 * Admits poll batches to a fixed sequence of stages. Each stage holds one batch at a time, and batches
 * pass through every stage in admission order. Neighbouring batches overlap in different stages, so a
 * stage that waits on I/O runs alongside a stage that uses the CPU, while no batch is delayed in a
 * stage by the work of a later batch in that same stage.
 */
export class BatchStages {
    private readonly limiters: Map<string, ReturnType<typeof pLimit>>
    // Once a batch fails, the batches behind it must not run further stages: their offsets would be tracked past the failed batch's messages, and the consumer stores whatever was tracked when it stops. Batches ahead of it finish, since their work is complete and in order.
    private failure: { sequence: number; error: unknown } | null = null
    private nextSequence = 0

    constructor(private readonly names: readonly string[]) {
        if (!names.length) {
            throw new Error('BatchStages needs at least one stage')
        }
        if (new Set(names).size !== names.length) {
            throw new Error(`BatchStages needs unique stage names, got ${names.join(', ')}`)
        }
        this.limiters = new Map(names.map((name) => [name, pLimit(1)]))
    }

    /** One batch per stage is the deepest the overlap goes. */
    public get lookahead(): number {
        return this.names.length
    }

    /** Admits one batch behind every batch admitted before it. Queue all of its stages in this same tick. */
    public admit(): AdmittedBatch<void> {
        const admission: Admission = { sequence: this.nextSequence++, open: true }
        queueMicrotask(() => (admission.open = false))
        return new AdmittedBatch(
            this,
            admission,
            0,
            Promise.resolve({ value: undefined, finishedAt: performance.now() })
        )
    }

    /** @internal Called through {@link AdmittedBatch.stage}. */
    public enter<T, U>(
        admission: Admission,
        index: number,
        name: string,
        previous: Promise<Timed<T>>,
        work: (input: T) => Promise<U>
    ): Promise<Timed<U>> {
        if (!admission.open) {
            throw new Error(`Batch queued stage '${name}' after the tick that admitted it`)
        }
        if (this.names[index] !== name) {
            throw new Error(`Batch entered stage '${name}' but stage ${index} is '${this.names[index] ?? 'none'}'`)
        }
        const limiter = this.limiters.get(name)!
        // The slot is taken while the batch is still in its previous stage. No other batch could use it, because the batch behind this one is still behind it in that previous stage.
        return limiter(async () => {
            const { value, finishedAt: readyAt } = await previous
            if (this.failure && admission.sequence > this.failure.sequence) {
                throw this.failure.error
            }
            const startedAt = performance.now()
            try {
                const result = await work(value)
                const finishedAt = performance.now()
                SessionRecordingIngesterMetrics.observeBatchStage(name, startedAt - readyAt, finishedAt - startedAt)
                return { value: result, finishedAt }
            } catch (error) {
                if (!this.failure || admission.sequence < this.failure.sequence) {
                    this.failure = { sequence: admission.sequence, error }
                }
                throw error
            }
        })
    }

    /** @internal Called through {@link AdmittedBatch.done}. */
    public assertComplete(index: number): void {
        if (index !== this.names.length) {
            throw new Error(
                `Batch finished after ${index} of ${this.names.length} stages, before '${this.names[index]}'`
            )
        }
    }
}

/** One admitted batch on its way through the stages; the output of each stage is the input of the next. */
export class AdmittedBatch<T> {
    constructor(
        private readonly stages: BatchStages,
        private readonly admission: Admission,
        private readonly index: number,
        private readonly previous: Promise<Timed<T>>
    ) {}

    /** Queues the batch for its next stage. The work starts once the batch has left the previous stage and the stage is free. */
    public stage<U>(name: string, work: (input: T) => Promise<U>): AdmittedBatch<U> {
        const next = this.stages.enter(this.admission, this.index, name, this.previous, work)
        // The rejection reaches the caller through the last stage, so an intermediate stage's promise must not count as unhandled while the batch waits for a slot.
        next.catch(() => undefined)
        return new AdmittedBatch(this.stages, this.admission, this.index + 1, next)
    }

    /** Resolves once the batch has left the last stage. Rejects with this batch's error, with the error of an earlier batch that failed, or if a stage was never queued. */
    public done(): Promise<T> {
        try {
            this.stages.assertComplete(this.index)
        } catch (error) {
            return Promise.reject(error)
        }
        return this.previous.then(({ value }) => value)
    }
}
