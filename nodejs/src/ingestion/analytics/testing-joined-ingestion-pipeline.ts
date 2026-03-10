import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { Team } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '../../utils/event-schema-enforcement-manager'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { AiEventOutput, EventOutput, IngestionOutputs } from '../event-processing/ingestion-outputs'
import { SplitAiEventsStepConfig } from '../event-processing/split-ai-events-step'
import { BatchPipelineBuilder } from '../pipelines/builders/batch-pipeline-builders'
import { OkResultWithContext } from '../pipelines/filter-map-batch-pipeline'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { ok } from '../pipelines/results'
import { createPreTeamPreprocessingSubpipeline } from './pre-team-preprocessing-subpipeline'
import {
    TestingPerDistinctIdPipelineConfig,
    TestingPerDistinctIdPipelineInput,
    createTestingPerDistinctIdPipeline,
} from './testing-per-distinct-id-pipeline'
import {
    TestingPostTeamPreprocessingSubpipelineConfig,
    TestingPostTeamPreprocessingSubpipelineInput,
    createTestingPostTeamPreprocessingSubpipeline,
} from './testing-post-team-preprocessing-subpipeline'

export interface TestingJoinedIngestionPipelineConfig {
    eventSchemaEnforcementEnabled: boolean
    overflowEnabled: boolean
    overflowTopic: string
    dlqTopic: string
    preservePartitionLocality: boolean
    groupId: string
    outputs: IngestionOutputs<EventOutput | AiEventOutput>
    splitAiEventsConfig: SplitAiEventsStepConfig
    perDistinctIdOptions: {
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: string
    }
}

export interface TestingJoinedIngestionPipelineDeps {
    kafkaProducer: KafkaProducerWrapper
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    eventSchemaEnforcementManager: EventSchemaEnforcementManager
    promiseScheduler: PromiseScheduler
    teamManager: TeamManager
}

export interface TestingJoinedIngestionPipelineInput {
    message: Message
}

export interface TestingJoinedIngestionPipelineContext {
    message: Message
}

type PreprocessingOutput = TestingPostTeamPreprocessingSubpipelineInput

function addTeamToContext<T extends { team: Team }, C>(
    element: OkResultWithContext<T, C>
): OkResultWithContext<T, C & { team: Team }> {
    return {
        result: element.result,
        context: {
            ...element.context,
            team: element.result.value.team,
        },
    }
}

function getTokenAndDistinctId(input: TestingPerDistinctIdPipelineInput): string {
    const token = input.headers.token ?? ''
    const distinctId = input.event.distinct_id ?? ''
    return `${token}:${distinctId}`
}

function mapToPerEventInput<C>(
    element: OkResultWithContext<PreprocessingOutput, C>
): OkResultWithContext<TestingPerDistinctIdPipelineInput, C> {
    const input = element.result.value
    return {
        result: ok({
            message: input.message,
            event: input.event,
            team: input.team,
            headers: input.headers,
        }),
        context: element.context,
    }
}

export function createTestingJoinedIngestionPipeline<
    TInput extends TestingJoinedIngestionPipelineInput,
    TContext extends TestingJoinedIngestionPipelineContext,
>(
    builder: BatchPipelineBuilder<TInput, TInput, TContext, TContext>,
    config: TestingJoinedIngestionPipelineConfig,
    deps: TestingJoinedIngestionPipelineDeps
) {
    const {
        eventSchemaEnforcementEnabled,
        overflowEnabled,
        overflowTopic,
        dlqTopic,
        preservePartitionLocality,
        groupId,
        outputs,
        splitAiEventsConfig,
        perDistinctIdOptions,
    } = config

    const { kafkaProducer, eventIngestionRestrictionManager, eventSchemaEnforcementManager, promiseScheduler } = deps

    const pipelineConfig: PipelineConfig = {
        kafkaProducer,
        dlqTopic,
        promiseScheduler,
    }

    const postTeamConfig: TestingPostTeamPreprocessingSubpipelineConfig = {
        eventSchemaEnforcementManager,
        eventSchemaEnforcementEnabled,
    }

    const perEventConfig: TestingPerDistinctIdPipelineConfig = {
        options: perDistinctIdOptions,
        outputs,
        splitAiEventsConfig,
        kafkaProducer,
        groupId,
    }

    // Compared to joined-ingestion-pipeline.ts:
    // CHANGED: uses createTestingPostTeamPreprocessingSubpipeline (no person prefetch, cookieless, or personless batch)
    // CHANGED: uses createTestingPerDistinctIdPipeline (no person/group processing in event branches)
    // REMOVED: createFlushBatchStoresStep (no person/group stores to flush)
    // REMOVED: personsStore, groupStore, cookielessManager, groupTypeManager from deps/config
    return builder
        .messageAware((b) =>
            b
                .sequentially((b) =>
                    createPreTeamPreprocessingSubpipeline(b, {
                        teamManager: deps.teamManager,
                        eventIngestionRestrictionManager,
                        overflowEnabled,
                        overflowTopic,
                        preservePartitionLocality,
                    })
                )
                .filterMap(addTeamToContext, (b) =>
                    b
                        .teamAware((b) =>
                            createTestingPostTeamPreprocessingSubpipeline(b, postTeamConfig)
                                .filterMap(mapToPerEventInput, (b) =>
                                    b
                                        .groupBy(getTokenAndDistinctId)
                                        .concurrently((eventsForDistinctId) =>
                                            eventsForDistinctId.sequentially((event) =>
                                                createTestingPerDistinctIdPipeline(event, perEventConfig)
                                            )
                                        )
                                )
                                .gather()
                        )
                        .handleIngestionWarnings(kafkaProducer)
                )
        )
        .handleResults(pipelineConfig)
        .handleSideEffects(promiseScheduler, { await: false })
}
