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
import { ChunkPipelineBuilder } from '~/ingestion/framework/builders/chunk-pipeline-builders'
import { PipelineBuilder, StartPipelineBuilder } from '~/ingestion/framework/builders/pipeline-builders'
import { PipelineConfig } from '~/ingestion/framework/result-handling-pipeline'
import { ok } from '~/ingestion/framework/results'
import { RetryOptions } from '~/ingestion/framework/retry'
import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, IncomingEvent, Team } from '~/types'

import { createParseHeadersStep, createParseKafkaMessageStep, createResolveTeamStep } from './steps/event-preprocessing'
import { addTeamToContext } from './subpipelines/helpers'

/**
 * Common ingestion pipeline builder.
 *
 * Every Kafka-fed ingestion pipeline (analytics, AI, error tracking, heatmaps,
 * client warnings, session replay) shares the same skeleton; only the steps in
 * the middle vary. This builder owns the skeleton and takes the varying parts
 * as typed callbacks, in the order they run:
 *
 * ```text
 * beforeBatch hooks                          .beforeBatch(cb)   (optional)
 *   messageAware
 *     parse headers                          (automatic)
 *     header-only per-event steps            .preParse(cb)
 *     pre-parse chunk steps                  .pipeChunk(step)   (optional, repeatable)
 *     parse body + resolve team              (automatic)
 *     post-resolution per-event steps        .resolveTeam(cb)
 *     lift team into context                 (automatic)
 *     teamAware
 *       product-specific processing          .perTeam(cb)
 *     handleIngestionWarnings                (automatic)
 *   handleResults                            (automatic)
 *   handleSideEffects                        (automatic)
 * afterBatch hooks                           .afterBatch(cb)    (optional)
 * ```
 *
 * The stages are enforced by the type system: each method returns the next
 * stage, so phases can't be reordered or forgotten. Redirect kinds are fixed
 * up front via the `ROut` type parameter — the configured outputs must cover
 * every redirect any step can produce.
 *
 * Note: `.preParse` and `.resolveTeam` each run as their own sequential block.
 * Pipelines that previously combined header and body steps in one block get
 * two blocks instead — per-element step order is unchanged, only the
 * interleaving across elements differs (all elements finish a block before the
 * next block starts pulling).
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

/** Element context inside the `.perTeam` block, after the team is lifted into it. */
type TeamAwareContext<TContext> = BatchContext<TContext> & { team: Team }

/** Output of the automatic parse-body + resolve-team chain, from which `.resolveTeam` continues. */
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

export type PreParseCallback<TInput, TContext, CBatch, THeaders, ROut extends string> = (
    builder: PipelineBuilder<
        BatchElement<TInput, CBatch>,
        BatchElement<TInput, CBatch> & { headers: EventHeaders },
        BatchContext<TContext>
    >
) => PipelineBuilder<BatchElement<TInput, CBatch>, THeaders, BatchContext<TContext>, ROut>

export type ResolveTeamCallback<TCurrent, TContext, TPost, ROut extends string> = (
    builder: PipelineBuilder<TCurrent, TeamResolved<TCurrent>, BatchContext<TContext>>
) => PipelineBuilder<TCurrent, TPost, BatchContext<TContext>, ROut>

export type PerTeamCallback<TPost, TContext, TFinal, ROut extends string> = (
    builder: ChunkPipelineBuilder<TPost, TPost, TeamAwareContext<TContext>, TeamAwareContext<TContext>>
) => ChunkPipelineBuilder<TPost, TFinal, TeamAwareContext<TContext>, TeamAwareContext<TContext>, ROut>

/**
 * The accumulated content of the messageAware block: a transform over the
 * batch sub-pipeline builder. Each stage extends the previous stage's
 * transform, so the skeleton is composed exactly once, at `.build()`.
 */
type SubpipelineTransform<TInput, TContext, CBatch, TOut, ROut extends string> = (
    builder: ChunkPipelineBuilder<
        BatchElement<TInput, CBatch>,
        BatchElement<TInput, CBatch>,
        BatchContext<TContext>,
        BatchContext<TContext>
    >
) => ChunkPipelineBuilder<BatchElement<TInput, CBatch>, TOut, BatchContext<TContext>, BatchContext<TContext>, ROut>

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
    ): CommonHeadersStage<TInput, TContext, ROut, CBatch> {
        return new CommonHeadersStage(this.config, callback)
    }

    /** Skip batch context and go straight to the header-only preprocessing block. */
    preParse<THeaders extends { message: Message; headers: EventHeaders }>(
        callback: PreParseCallback<TInput, TContext, Record<never, object>, THeaders, ROut>
    ): CommonPreParseStage<TInput, TContext, ROut, Record<never, object>, THeaders> {
        return this.beforeBatch<Record<never, object>>((builder) =>
            builder.pipe(function passThroughBeforeBatch(input) {
                return Promise.resolve(ok(input))
            })
        ).preParse(callback)
    }
}

export class CommonHeadersStage<
    TInput extends { message: Message },
    TContext extends { message: Message },
    ROut extends string,
    CBatch,
> {
    constructor(
        private readonly config: CommonIngestionPipelineConfig<ROut>,
        private readonly beforeBatchCallback: BeforeBatchCallback<TInput, TContext, CBatch>
    ) {}

    /**
     * Header-only per-event steps (allow/deny lists, token restrictions).
     * Headers are already parsed; the message body is not.
     */
    preParse<THeaders extends { message: Message; headers: EventHeaders }>(
        callback: PreParseCallback<TInput, TContext, CBatch, THeaders, ROut>
    ): CommonPreParseStage<TInput, TContext, ROut, CBatch, THeaders> {
        return new CommonPreParseStage(this.config, this.beforeBatchCallback, (builder) =>
            builder.sequentially((b) => callback(b.pipe(createParseHeadersStep())))
        )
    }
}

export class CommonPreParseStage<
    TInput extends { message: Message },
    TContext extends { message: Message },
    ROut extends string,
    CBatch,
    TCurrent extends { message: Message; headers: EventHeaders },
> {
    constructor(
        private readonly config: CommonIngestionPipelineConfig<ROut>,
        private readonly beforeBatchCallback: BeforeBatchCallback<TInput, TContext, CBatch>,
        private readonly transform: SubpipelineTransform<TInput, TContext, CBatch, TCurrent, ROut>
    ) {}

    /**
     * Chunk steps that run after the header block but before the body is
     * parsed (e.g. rate-limit-to-overflow, which redirects on headers alone).
     */
    pipeChunk<U extends { message: Message; headers: EventHeaders }, R2 extends ROut>(
        step: ChunkProcessingStep<TCurrent, U, R2>,
        options?: { retry?: RetryOptions }
    ): CommonPreParseStage<TInput, TContext, ROut, CBatch, U> {
        return new CommonPreParseStage(this.config, this.beforeBatchCallback, (builder) =>
            this.transform(builder).pipeChunk(step, options)
        )
    }

    /**
     * Parse the message body and resolve the team (automatic), then run the
     * post-resolution per-event steps supplied by the callback (validation,
     * settings loads — anything that needs the parsed event and team but not
     * yet the team in context).
     */
    resolveTeam<TPost extends { team: Team }>(
        callback: ResolveTeamCallback<TCurrent, TContext, TPost, ROut>
    ): CommonPerTeamStage<TInput, TContext, ROut, CBatch, TPost> {
        const { teamManager } = this.config
        return new CommonPerTeamStage(this.config, this.beforeBatchCallback, (builder) =>
            this.transform(builder).sequentially((b) =>
                callback(b.pipe(createParseKafkaMessageStep()).pipe(createResolveTeamStep(teamManager)))
            )
        )
    }
}

export class CommonPerTeamStage<
    TInput extends { message: Message },
    TContext extends { message: Message },
    ROut extends string,
    CBatch,
    TPost extends { team: Team },
> {
    constructor(
        private readonly config: CommonIngestionPipelineConfig<ROut>,
        private readonly beforeBatchCallback: BeforeBatchCallback<TInput, TContext, CBatch>,
        private readonly transform: SubpipelineTransform<TInput, TContext, CBatch, TPost, ROut>
    ) {}

    /**
     * The product-specific processing block. Runs team-aware: the team is
     * lifted into the element context (so ingestion warnings route to it) and
     * warnings are handled when the block completes. The callback gets the
     * full batch builder — sequential chains, gather/pipeBatch, and
     * concurrentlyPerGroup all compose as usual.
     */
    perTeam<TFinal>(
        callback: PerTeamCallback<TPost, TContext, TFinal, ROut>
    ): CommonBuildStage<TInput, TContext, ROut, CBatch, TFinal> {
        const { outputs } = this.config
        return new CommonBuildStage(this.config, this.beforeBatchCallback, (builder) =>
            this.transform(builder).filterMap(addTeamToContext, (b) =>
                b.teamAware((teamAware) => callback(teamAware)).handleIngestionWarnings(outputs)
            )
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

    /** Flush steps that run once per batch after every element has a result. */
    afterBatch(
        callback: AfterBatchCallback<TFinal, TContext, CBatch, ROut>
    ): CommonBuildStage<TInput, TContext, ROut, CBatch, TFinal> {
        return new CommonBuildStage(this.config, this.beforeBatchCallback, this.transform, callback)
    }

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
