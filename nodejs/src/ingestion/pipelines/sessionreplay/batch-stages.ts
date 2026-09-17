import pLimit from 'p-limit'

import { SessionRecordingIngesterMetrics } from './metrics'

type Timed<T> = { value: T; finishedAt: number }

/** Open during the tick that admits the batch. The batch must queue all of its stages before the tick ends. If it queues a stage later, a later batch can enter that stage first. */
type Admission = { sequence: number; open: boolean }

/**
 * Admits poll batches to a fixed sequence of stages. Each stage holds one batch at a time. Batches pass
 * through every stage in admission order. Two batches can be in two different stages at the same time,
 * so a stage that waits on I/O runs while another stage uses the CPU. A later batch never delays an
 * earlier batch in the same stage.
 */
export class BatchStages {
    private readonly limiters: Map<string, ReturnType<typeof pLimit>>
    // When a batch fails, the batches behind it must not run more stages. Their offsets would go past the messages of the failed batch, and the consumer stores the tracked offsets when it stops. The batches ahead of the failed batch complete, because their work is complete and in order. The consumer decides whether to admit a batch after the failure, as it does for a lane that does not overlap batches.
    private failure: { sequence: number; lastAdmitted: number; error: unknown } | null = null
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

    /** The most batches that can be in flight at the same time: one for each stage. */
    public get lookahead(): number {
        return this.names.length
    }

    /** Admits one batch after all the batches admitted before it. Queue all of its stages in the same tick. */
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
        // The batch takes the slot while it is still in its previous stage. No other batch can use the slot, because the next batch is still behind this batch in that previous stage.
        return limiter(async () => {
            const { value, finishedAt: readyAt } = await previous
            if (
                this.failure &&
                admission.sequence > this.failure.sequence &&
                admission.sequence <= this.failure.lastAdmitted
            ) {
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
                    this.failure = { sequence: admission.sequence, lastAdmitted: this.nextSequence - 1, error }
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

/** One admitted batch that moves through the stages. The output of each stage is the input of the next stage. */
export class AdmittedBatch<T> {
    constructor(
        private readonly stages: BatchStages,
        private readonly admission: Admission,
        private readonly index: number,
        private readonly previous: Promise<Timed<T>>
    ) {}

    /** Queues the batch for its next stage. The work starts when the batch leaves the previous stage and the next stage is free. */
    public stage<U>(name: string, work: (input: T) => Promise<U>): AdmittedBatch<U> {
        const next = this.stages.enter(this.admission, this.index, name, this.previous, work)
        // The rejection reaches the caller through the last stage. The promise of an earlier stage must not count as unhandled while the batch waits for a slot.
        next.catch(() => undefined)
        return new AdmittedBatch(this.stages, this.admission, this.index + 1, next)
    }

    /** Resolves when the batch leaves the last stage. Rejects with the error of this batch, with the error of an earlier batch that failed, or with an error if the batch did not queue all of its stages. */
    public done(): Promise<T> {
        try {
            this.stages.assertComplete(this.index)
        } catch (error) {
            return Promise.reject(error)
        }
        return this.previous.then(({ value }) => value)
    }
}
