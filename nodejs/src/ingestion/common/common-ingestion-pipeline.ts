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
 * route to the resolved team. The warning handler only covers that scope:
 * warnings attached to non-OK results before `.resolveTeam()` are silently
 * dropped (there is no team to route them to), so pre-team steps must attach
 * warnings to OK results only. The stages are enforced by the type system —
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
    /**
     * Await side effects inline instead of scheduling them on the promise
     * scheduler. Applies to element results and to the beforeBatch/afterBatch
     * hooks alike — the built pipeline always handles its own side effects, so
     * drivers never see them on `BatchResult.sideEffects`. Defaults to false.
     */
    awaitSideEffects?: boolean
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
 * A phase's accumulated content: a transform over the phase's chunk builder,
 * from the phase's start element type `TStart` to the current element type,
 * under the element context `C`. Each call extends the previous transform,
 * so the skeleton is composed exactly once, at `.build()`.
 */
type ChainTransform<TStart, TCurrent, C, ROut extends string> = (
    builder: ChunkPipelineBuilder<TStart, TStart, C, C>
) => ChunkPipelineBuilder<TStart, TCurrent, C, C, ROut>

/** The messageAware block before `.resolveTeam()`: runs under the batch context. */
type SubpipelineTransform<TInput, TContext, CBatch, TOut, ROut extends string> = ChainTransform<
    BatchElement<TInput, CBatch>,
    TOut,
    BatchContext<TContext>,
    ROut
>

/**
 * Coalesces consecutive per-element steps into one sequential block. `extend`
 * appends a step to the open block (or opens one); `build` closes it into the
 * committed chunk-level transform. The block's start type stays existential —
 * it lives only in the closures — so stages don't carry it as a type parameter.
 *
 * Both builder phases share this mechanism and differ only in instantiation:
 * the pre-team phase runs under the batch context, the team-aware phase under
 * the team-lifted context (see the aliases below).
 */
interface Chain<TStart, C, ROut extends string, TCurrent> {
    build(): ChainTransform<TStart, TCurrent, C, ROut>
    extend<U, R2 extends ROut>(
        step: ProcessingStep<TCurrent, U, R2>,
        options?: { retry?: RetryOptions }
    ): Chain<TStart, C, ROut, U>
}

function pendingChain<TStart, C, ROut extends string, TBlock, TCurrent>(
    committed: ChainTransform<TStart, TBlock, C, ROut>,
    pending: (start: StartPipelineBuilder<TBlock, C>) => PipelineBuilder<TBlock, TCurrent, C, ROut>
): Chain<TStart, C, ROut, TCurrent> {
    return {
        build: () => (builder) => committed(builder).sequentially(pending),
        extend: (step, options) => pendingChain(committed, (start) => pending(start).pipe(step, options)),
    }
}

function committedChain<TStart, C, ROut extends string, TCurrent>(
    committed: ChainTransform<TStart, TCurrent, C, ROut>
): Chain<TStart, C, ROut, TCurrent> {
    return {
        build: () => committed,
        extend: (step, options) => pendingChain(committed, (start) => start.pipe(step, options)),
    }
}

/** Chain over the pre-team phase. */
type PreTeamChain<TInput, TContext, ROut extends string, CBatch, TCurrent> = Chain<
    BatchElement<TInput, CBatch>,
    BatchContext<TContext>,
    ROut,
    TCurrent
>

/** Chain over the team-aware phase. */
type TeamChain<TPost, TContext, ROut extends string, TCurrent> = Chain<
    TPost,
    TeamAwareContext<TContext>,
    ROut,
    TCurrent
>

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
            pendingChain<
                BatchElement<TInput, CBatch>,
                BatchContext<TContext>,
                ROut,
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
            committedChain((builder) => committed(builder).pipeChunk(step, options))
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
            committedChain((builder) => builder)
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
            committedChain((builder) => committed(builder).pipeChunk(step, options))
        )
    }

    /** Re-collect concurrent groups or streamed elements into one chunk. */
    gather(): CommonTeamStage<TInput, TContext, ROut, CBatch, TPost, TCurrent> {
        const committed = this.chain.build()
        return new CommonTeamStage(
            this.config,
            this.beforeBatchCallback,
            this.preTeamTransform,
            committedChain((builder) => committed(builder).gather())
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
            committedChain((builder) => committed(builder).concurrentlyPerGroup(groupingFn, callback, options))
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
            committedChain((builder) => fn(committed(builder)))
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
        const { outputs, promiseScheduler, concurrentBatches, awaitSideEffects } = this.config
        const pipelineConfig: PipelineConfig<ROut> = { outputs, promiseScheduler }
        const sideEffectOptions = { await: awaitSideEffects ?? false }
        const afterBatchCallback: AfterBatchCallback<TFinal, TContext, CBatch, ROut> =
            this.afterBatchCallback ??
            ((builder) =>
                builder.pipe(function passThroughAfterBatch(input) {
                    return Promise.resolve(ok(input))
                }))

        // The hooks handle their own side effects, so nothing rides out on
        // `BatchResult.sideEffects` and drivers only ever drain results.
        return newBatchingPipeline<TInput, TFinal, TContext, CBatch, TContext, ROut>(
            (builder) => this.beforeBatchCallback(builder).handleSideEffects(promiseScheduler, sideEffectOptions),
            (batch) =>
                batch
                    .messageAware((b) => this.transform(b))
                    .handleResults(pipelineConfig)
                    .handleSideEffects(promiseScheduler, sideEffectOptions),
            (builder) => afterBatchCallback(builder).handleSideEffects(promiseScheduler, sideEffectOptions),
            concurrentBatches === undefined ? undefined : { concurrentBatches }
        )
    }
}
