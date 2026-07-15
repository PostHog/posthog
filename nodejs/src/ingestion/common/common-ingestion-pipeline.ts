import { Message } from 'node-rdkafka'

import { DlqOutput, IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { TeamManager } from '~/common/utils/team-manager'
import { ChunkProcessingStep } from '~/ingestion/framework/base-chunk-pipeline'
import {
    AfterBatchInput,
    AfterBatchOutput,
    BatchingContext,
    BatchingPipeline,
    BeforeBatchInput,
    BeforeBatchOutput,
} from '~/ingestion/framework/batching-pipeline'
import { newBatchingPipeline } from '~/ingestion/framework/builders'
import { ChunkPipelineBuilder, GroupProcessingBuilder } from '~/ingestion/framework/builders/chunk-pipeline-builders'
import { PipelineBuilder, StartPipelineBuilder } from '~/ingestion/framework/builders/pipeline-builders'
import { GroupingFunction } from '~/ingestion/framework/concurrently-grouping-chunk-pipeline'
import { PipelineConfig } from '~/ingestion/framework/result-handling-pipeline'
import { ok } from '~/ingestion/framework/results'
import { RetryOptions } from '~/ingestion/framework/retry'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, IncomingEvent, Team } from '~/types'

import { createParseHeadersStep, createParseKafkaMessageStep, createResolveTeamStep } from './steps/event-preprocessing'
import { addTeamToContext } from './subpipelines/helpers'

/**
 * Common ingestion pipeline builder.
 *
 * Every Kafka-fed ingestion pipeline (analytics, AI, error tracking, heatmaps,
 * client warnings, session replay) shares the same skeleton; only the steps in
 * the middle vary. This builder owns the skeleton and reads as a flat recipe —
 * the phase markers carry the structure:
 *
 * ```text
 * beforeBatch hooks                            .beforeBatch(cb)   (optional)
 *   messageAware
 *     parse headers                            .parseHeaders()
 *     header-only steps                        .pipe / .pipeChunk
 *     parse body                               .parseMessage()
 *     body steps                               .pipe
 *     resolve team, lift team into context     .resolveTeam()
 *     team-aware processing                    .pipe / .pipeChunk / .gather /
 *                                              .concurrentlyPerGroup / .compose
 *     handleIngestionWarnings                  (automatic)
 *   handleResults                              (automatic)
 *   handleSideEffects                          (automatic)
 * afterBatch hooks                             .afterBatch(cb)    (optional)
 * ```
 *
 * Consecutive `.pipe()` calls coalesce into one sequential per-element block;
 * any chunk-level call (`.pipeChunk`, `.gather`, `.concurrentlyPerGroup`,
 * `.compose`, a phase marker that is chunk-level) closes the block. Block
 * boundaries therefore fall out of where the chunk operations sit, which is
 * how the hand-written pipelines were already shaped.
 *
 * `.resolveTeam()` resolves the team, lifts it into the element context, and
 * opens the team-aware scope: every step after it runs inside
 * `handleIngestionWarnings`, so warnings (and warnings on dropped elements)
 * route to the resolved team. The stages are enforced by the type system —
 * body steps don't typecheck before `.parseMessage()`, team-dependent steps
 * not before `.resolveTeam()`. Redirect kinds are fixed up front via the
 * `ROut` type parameter — the configured outputs must cover every redirect any
 * step can produce.
 */
export interface CommonIngestionPipelineConfig<ROut extends string = never> {
    teamManager: TeamManager
    outputs: IngestionOutputs<IngestionWarningsOutput | DlqOutput | ROut>
    promiseScheduler: PromiseScheduler
    /** Maximum number of batches accepted concurrently. Defaults to the framework default. */
    concurrentBatches?: number
}

/** Element type entering the per-batch sub-pipeline: input enriched by the beforeBatch hooks. */
type BatchElement<TInput, CBatch> = TInput & CBatch

/** Element context inside the per-batch sub-pipeline. */
type BatchContext<TContext> = TContext & BatchingContext

/** Element context after `.resolveTeam()`, once the team is lifted into it. */
type TeamAwareContext<TContext> = BatchContext<TContext> & { team: Team }

/** Output of `.resolveTeam()`: the parsed event with the resolved team attached. */
type TeamResolved<T> = Omit<T & { event: IncomingEvent }, 'event'> & { event: PluginEvent; team: Team }

export type BeforeBatchCallback<TInput, TContext, CBatch> = (
    builder: StartPipelineBuilder<BeforeBatchInput<TInput, TContext>, Record<string, never>>
) => PipelineBuilder<
    BeforeBatchInput<TInput, TContext>,
    BeforeBatchOutput<TInput, TContext, CBatch>,
    Record<string, never>
>

export type AfterBatchCallback<TOutput, TContext, CBatch, ROut extends string> = (
    builder: StartPipelineBuilder<AfterBatchInput<TOutput, BatchContext<TContext>, CBatch, ROut>, Record<string, never>>
) => PipelineBuilder<
    AfterBatchInput<TOutput, BatchContext<TContext>, CBatch, ROut>,
    AfterBatchOutput<TOutput, BatchContext<TContext>, CBatch, ROut>,
    Record<string, never>
>

/**
 * The accumulated content of the messageAware block before `.resolveTeam()`:
 * a transform over the batch sub-pipeline builder. Each call extends the
 * previous transform, so the skeleton is composed exactly once, at `.build()`.
 */
type SubpipelineTransform<TInput, TContext, CBatch, TOut, ROut extends string> = (
    builder: ChunkPipelineBuilder<
        BatchElement<TInput, CBatch>,
        BatchElement<TInput, CBatch>,
        BatchContext<TContext>,
        BatchContext<TContext>
    >
) => ChunkPipelineBuilder<BatchElement<TInput, CBatch>, TOut, BatchContext<TContext>, BatchContext<TContext>, ROut>

/** The accumulated team-aware content after `.resolveTeam()`, nested inside the team lift at `.build()`. */
type TeamSubpipelineTransform<TPost, TContext, TCurrent, ROut extends string> = (
    builder: ChunkPipelineBuilder<TPost, TPost, TeamAwareContext<TContext>, TeamAwareContext<TContext>>
) => ChunkPipelineBuilder<TPost, TCurrent, TeamAwareContext<TContext>, TeamAwareContext<TContext>, ROut>

/**
 * Coalesces consecutive per-element steps into one sequential block. `extend`
 * appends a step to the open block (or opens one); `build` closes it into the
 * committed chunk-level transform. The block's start type stays existential —
 * it lives only in the closures — so stages don't carry it as a type parameter.
 */
interface PreTeamChain<TInput, TContext, ROut extends string, CBatch, TCurrent> {
    build(): SubpipelineTransform<TInput, TContext, CBatch, TCurrent, ROut>
    extend<U, R2 extends ROut>(
        step: ProcessingStep<TCurrent, U, R2>,
        options?: { retry?: RetryOptions }
    ): PreTeamChain<TInput, TContext, ROut, CBatch, U>
}

function pendingPreTeamChain<TInput, TContext, ROut extends string, CBatch, TBlock, TCurrent>(
    committed: SubpipelineTransform<TInput, TContext, CBatch, TBlock, ROut>,
    pending: (
        start: StartPipelineBuilder<TBlock, BatchContext<TContext>>
    ) => PipelineBuilder<TBlock, TCurrent, BatchContext<TContext>, ROut>
): PreTeamChain<TInput, TContext, ROut, CBatch, TCurrent> {
    return {
        build: () => (builder) => committed(builder).sequentially(pending),
        extend: (step, options) => pendingPreTeamChain(committed, (start) => pending(start).pipe(step, options)),
    }
}

function committedPreTeamChain<TInput, TContext, ROut extends string, CBatch, TCurrent>(
    committed: SubpipelineTransform<TInput, TContext, CBatch, TCurrent, ROut>
): PreTeamChain<TInput, TContext, ROut, CBatch, TCurrent> {
    return {
        build: () => committed,
        extend: (step, options) => pendingPreTeamChain(committed, (start) => start.pipe(step, options)),
    }
}

/** Same coalescing for the team-aware phase, over the inner (post-lift) builder. */
interface TeamChain<TPost, TContext, ROut extends string, TCurrent> {
    build(): TeamSubpipelineTransform<TPost, TContext, TCurrent, ROut>
    extend<U, R2 extends ROut>(
        step: ProcessingStep<TCurrent, U, R2>,
        options?: { retry?: RetryOptions }
    ): TeamChain<TPost, TContext, ROut, U>
}

function pendingTeamChain<TPost, TContext, ROut extends string, TBlock, TCurrent>(
    committed: TeamSubpipelineTransform<TPost, TContext, TBlock, ROut>,
    pending: (
        start: StartPipelineBuilder<TBlock, TeamAwareContext<TContext>>
    ) => PipelineBuilder<TBlock, TCurrent, TeamAwareContext<TContext>, ROut>
): TeamChain<TPost, TContext, ROut, TCurrent> {
    return {
        build: () => (builder) => committed(builder).sequentially(pending),
        extend: (step, options) => pendingTeamChain(committed, (start) => pending(start).pipe(step, options)),
    }
}

function committedTeamChain<TPost, TContext, ROut extends string, TCurrent>(
    committed: TeamSubpipelineTransform<TPost, TContext, TCurrent, ROut>
): TeamChain<TPost, TContext, ROut, TCurrent> {
    return {
        build: () => committed,
        extend: (step, options) => pendingTeamChain(committed, (start) => start.pipe(step, options)),
    }
}

export function newCommonIngestionPipeline<
    TInput extends { message: Message },
    TContext extends { message: Message },
    ROut extends string = never,
>(config: CommonIngestionPipelineConfig<ROut>): CommonIngestionPipelineBuilder<TInput, TContext, ROut> {
    return new CommonIngestionPipelineBuilder(config)
}

export class CommonIngestionPipelineBuilder<
    TInput extends { message: Message },
    TContext extends { message: Message },
    ROut extends string,
> {
    constructor(private readonly config: CommonIngestionPipelineConfig<ROut>) {}

    /** Attach batch context (e.g. batch-scoped stores) before each batch is processed. */
    beforeBatch<CBatch>(
        callback: BeforeBatchCallback<TInput, TContext, CBatch>
    ): CommonBatchHooksStage<TInput, TContext, ROut, CBatch> {
        return new CommonBatchHooksStage(this.config, callback)
    }

    /** Skip batch context and go straight to header parsing. */
    parseHeaders(): CommonPreTeamStage<
        TInput,
        TContext,
        ROut,
        Record<never, object>,
        BatchElement<TInput, Record<never, object>> & { headers: EventHeaders }
    > {
        return this.beforeBatch<Record<never, object>>((builder) =>
            builder.pipe(function passThroughBeforeBatch(input) {
                return Promise.resolve(ok(input))
            })
        ).parseHeaders()
    }
}

export class CommonBatchHooksStage<
    TInput extends { message: Message },
    TContext extends { message: Message },
    ROut extends string,
    CBatch,
> {
    constructor(
        private readonly config: CommonIngestionPipelineConfig<ROut>,
        private readonly beforeBatchCallback: BeforeBatchCallback<TInput, TContext, CBatch>
    ) {}

    /** Parse Kafka headers; after this, header-shaped steps can be piped. */
    parseHeaders(): CommonPreTeamStage<
        TInput,
        TContext,
        ROut,
        CBatch,
        BatchElement<TInput, CBatch> & { headers: EventHeaders }
    > {
        return new CommonPreTeamStage(
            this.config,
            this.beforeBatchCallback,
            pendingPreTeamChain<
                TInput,
                TContext,
                ROut,
                CBatch,
                BatchElement<TInput, CBatch>,
                BatchElement<TInput, CBatch> & { headers: EventHeaders }
            >(
                (builder) => builder,
                (start) => start.pipe(createParseHeadersStep())
            )
        )
    }
}

export class CommonPreTeamStage<
    TInput extends { message: Message },
    TContext extends { message: Message },
    ROut extends string,
    CBatch,
    TCurrent extends { message: Message; headers: EventHeaders },
> {
    constructor(
        private readonly config: CommonIngestionPipelineConfig<ROut>,
        private readonly beforeBatchCallback: BeforeBatchCallback<TInput, TContext, CBatch>,
        private readonly chain: PreTeamChain<TInput, TContext, ROut, CBatch, TCurrent>
    ) {}

    /** Per-element step; consecutive pipes run in one sequential block. */
    pipe<U extends { message: Message; headers: EventHeaders }, R2 extends ROut>(
        step: ProcessingStep<TCurrent, U, R2>,
        options?: { retry?: RetryOptions }
    ): CommonPreTeamStage<TInput, TContext, ROut, CBatch, U> {
        return new CommonPreTeamStage(this.config, this.beforeBatchCallback, this.chain.extend(step, options))
    }

    /** Chunk-level step (e.g. rate-limit-to-overflow); closes the open sequential block. */
    pipeChunk<U extends { message: Message; headers: EventHeaders }, R2 extends ROut>(
        step: ChunkProcessingStep<TCurrent, U, R2>,
        options?: { retry?: RetryOptions }
    ): CommonPreTeamStage<TInput, TContext, ROut, CBatch, U> {
        const committed = this.chain.build()
        return new CommonPreTeamStage(
            this.config,
            this.beforeBatchCallback,
            committedPreTeamChain((builder) => committed(builder).pipeChunk(step, options))
        )
    }

    /** Parse the message body; after this, body-dependent steps can be piped. */
    parseMessage(): CommonPreTeamStage<TInput, TContext, ROut, CBatch, TCurrent & { event: IncomingEvent }> {
        return this.pipe(createParseKafkaMessageStep())
    }

    /**
     * Resolve the team from the token, lift it into the element context, and
     * open the team-aware scope: every step piped after this runs inside
     * `handleIngestionWarnings`, with warnings routed to the resolved team.
     *
     * `options.wrap` decorates the team-resolution step while preserving its
     * types — e.g. a topHog metrics wrapper.
     */
    resolveTeam(
        this: CommonPreTeamStage<TInput, TContext, ROut, CBatch, TCurrent & { event: IncomingEvent }>,
        options?: {
            wrap?: (
                step: ProcessingStep<TCurrent & { event: IncomingEvent }, TeamResolved<TCurrent>>
            ) => ProcessingStep<TCurrent & { event: IncomingEvent }, TeamResolved<TCurrent>, ROut>
        }
    ): CommonTeamStage<TInput, TContext, ROut, CBatch, TeamResolved<TCurrent>, TeamResolved<TCurrent>> {
        const step = createResolveTeamStep<TCurrent & { event: IncomingEvent }>(this.config.teamManager)
        const resolved = this.chain.extend(options?.wrap ? options.wrap(step) : step)
        return new CommonTeamStage(
            this.config,
            this.beforeBatchCallback,
            resolved.build(),
            committedTeamChain((builder) => builder)
        )
    }
}

export class CommonTeamStage<
    TInput extends { message: Message },
    TContext extends { message: Message },
    ROut extends string,
    CBatch,
    TPost extends { team: Team },
    TCurrent,
> {
    constructor(
        private readonly config: CommonIngestionPipelineConfig<ROut>,
        private readonly beforeBatchCallback: BeforeBatchCallback<TInput, TContext, CBatch>,
        private readonly preTeamTransform: SubpipelineTransform<TInput, TContext, CBatch, TPost, ROut>,
        private readonly chain: TeamChain<TPost, TContext, ROut, TCurrent>
    ) {}

    /** Per-element step; consecutive pipes run in one sequential block. */
    pipe<U, R2 extends ROut>(
        step: ProcessingStep<TCurrent, U, R2>,
        options?: { retry?: RetryOptions }
    ): CommonTeamStage<TInput, TContext, ROut, CBatch, TPost, U> {
        return new CommonTeamStage(
            this.config,
            this.beforeBatchCallback,
            this.preTeamTransform,
            this.chain.extend(step, options)
        )
    }

    /** Chunk-level step; closes the open sequential block. */
    pipeChunk<U, R2 extends ROut>(
        step: ChunkProcessingStep<TCurrent, U, R2>,
        options?: { retry?: RetryOptions }
    ): CommonTeamStage<TInput, TContext, ROut, CBatch, TPost, U> {
        const committed = this.chain.build()
        return new CommonTeamStage(
            this.config,
            this.beforeBatchCallback,
            this.preTeamTransform,
            committedTeamChain((builder) => committed(builder).pipeChunk(step, options))
        )
    }

    /** Re-collect concurrent groups or streamed elements into one chunk. */
    gather(): CommonTeamStage<TInput, TContext, ROut, CBatch, TPost, TCurrent> {
        const committed = this.chain.build()
        return new CommonTeamStage(
            this.config,
            this.beforeBatchCallback,
            this.preTeamTransform,
            committedTeamChain((builder) => committed(builder).gather())
        )
    }

    /**
     * Group elements by key and process the groups concurrently; the callback
     * configures how items within a group are processed (mirrors the framework
     * method — within-group ordering stays visible at the call site).
     */
    concurrentlyPerGroup<TKey, U>(
        groupingFn: GroupingFunction<TCurrent, TKey>,
        callback: (
            group: GroupProcessingBuilder<TPost, TCurrent, TeamAwareContext<TContext>, TeamAwareContext<TContext>, ROut>
        ) => ChunkPipelineBuilder<TPost, U, TeamAwareContext<TContext>, TeamAwareContext<TContext>, ROut>,
        options?: { maxConcurrency?: number }
    ): CommonTeamStage<TInput, TContext, ROut, CBatch, TPost, U> {
        const committed = this.chain.build()
        return new CommonTeamStage(
            this.config,
            this.beforeBatchCallback,
            this.preTeamTransform,
            committedTeamChain((builder) => committed(builder).concurrentlyPerGroup(groupingFn, callback, options))
        )
    }

    /** Escape hatch: apply a subpipeline function (a transform over the chunk builder). */
    compose<U>(
        fn: (
            builder: ChunkPipelineBuilder<TPost, TCurrent, TeamAwareContext<TContext>, TeamAwareContext<TContext>, ROut>
        ) => ChunkPipelineBuilder<TPost, U, TeamAwareContext<TContext>, TeamAwareContext<TContext>, ROut>
    ): CommonTeamStage<TInput, TContext, ROut, CBatch, TPost, U> {
        const committed = this.chain.build()
        return new CommonTeamStage(
            this.config,
            this.beforeBatchCallback,
            this.preTeamTransform,
            committedTeamChain((builder) => fn(committed(builder)))
        )
    }

    /** Flush steps that run once per batch after every element has a result. */
    afterBatch(
        callback: AfterBatchCallback<TCurrent, TContext, CBatch, ROut>
    ): CommonBuildStage<TInput, TContext, ROut, CBatch, TCurrent> {
        return new CommonBuildStage(this.config, this.beforeBatchCallback, this.completeTransform(), callback)
    }

    build(): BatchingPipeline<TInput, TCurrent, TContext, CBatch, BatchContext<TContext>, ROut> {
        return new CommonBuildStage(this.config, this.beforeBatchCallback, this.completeTransform()).build()
    }

    private completeTransform(): SubpipelineTransform<TInput, TContext, CBatch, TCurrent, ROut> {
        const { outputs } = this.config
        const preTeam = this.preTeamTransform
        const inner = this.chain.build()
        return (builder) =>
            preTeam(builder).filterMap(addTeamToContext, (b) =>
                b.teamAware((teamAware) => inner(teamAware)).handleIngestionWarnings(outputs)
            )
    }
}

export class CommonBuildStage<
    TInput extends { message: Message },
    TContext extends { message: Message },
    ROut extends string,
    CBatch,
    TFinal,
> {
    constructor(
        private readonly config: CommonIngestionPipelineConfig<ROut>,
        private readonly beforeBatchCallback: BeforeBatchCallback<TInput, TContext, CBatch>,
        private readonly transform: SubpipelineTransform<TInput, TContext, CBatch, TFinal, ROut>,
        private readonly afterBatchCallback?: AfterBatchCallback<TFinal, TContext, CBatch, ROut>
    ) {}

    build(): BatchingPipeline<TInput, TFinal, TContext, CBatch, BatchContext<TContext>, ROut> {
        const { outputs, promiseScheduler, concurrentBatches } = this.config
        const pipelineConfig: PipelineConfig<ROut> = { outputs, promiseScheduler }
        const afterBatchCallback: AfterBatchCallback<TFinal, TContext, CBatch, ROut> =
            this.afterBatchCallback ??
            ((builder) =>
                builder.pipe(function passThroughAfterBatch(input) {
                    return Promise.resolve(ok(input))
                }))

        return newBatchingPipeline<TInput, TFinal, TContext, CBatch, TContext, ROut>(
            this.beforeBatchCallback,
            (batch) =>
                batch
                    .messageAware((b) => this.transform(b))
                    .handleResults(pipelineConfig)
                    .handleSideEffects(promiseScheduler, { await: false }),
            afterBatchCallback,
            concurrentBatches === undefined ? undefined : { concurrentBatches }
        )
    }
}
