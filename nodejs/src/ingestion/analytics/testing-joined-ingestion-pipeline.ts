import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { Team } from '../../types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { EventOutput, IngestionOutputs } from '../event-processing/ingestion-outputs'
import { BatchPipelineBuilder } from '../pipelines/builders/batch-pipeline-builders'
import { OkResultWithContext } from '../pipelines/filter-map-batch-pipeline'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { ok } from '../pipelines/results'
import {
    TestingPerDistinctIdPipelineConfig,
    TestingPerDistinctIdPipelineInput,
    createTestingPerDistinctIdPipeline,
} from './testing-per-distinct-id-pipeline'
import {
    TestingPostTeamPreprocessingSubpipelineInput,
    createTestingPostTeamPreprocessingSubpipeline,
} from './testing-post-team-preprocessing-subpipeline'
import { createTestingPreTeamPreprocessingSubpipeline } from './testing-pre-team-preprocessing-subpipeline'

export interface TestingJoinedIngestionPipelineConfig {
    dlqTopic: string
    groupId: string
    outputs: IngestionOutputs<EventOutput>
    personsPrefetchEnabled: boolean
    perDistinctIdOptions: {
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: string
    }
}

export interface TestingJoinedIngestionPipelineDeps {
    kafkaProducer: KafkaProducerWrapper
    personsStore: PersonsStore
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
    const { dlqTopic, groupId, outputs, personsPrefetchEnabled, perDistinctIdOptions } = config

    const { kafkaProducer, personsStore, promiseScheduler } = deps

    const pipelineConfig: PipelineConfig = {
        kafkaProducer,
        dlqTopic,
        promiseScheduler,
    }

    const perEventConfig: TestingPerDistinctIdPipelineConfig = {
        options: perDistinctIdOptions,
        outputs,
        personsStore,
        kafkaProducer,
        groupId,
    }

    // Compared to joined-ingestion-pipeline.ts:
    // CHANGED: uses createTestingPostTeamPreprocessingSubpipeline (prefetch persons, but no cookieless or personless batch)
    // CHANGED: uses createTestingPerDistinctIdPipeline (readonly person processing, no group processing)
    // REMOVED: createFlushBatchStoresStep (no person/group stores to flush — persons are read-only)
    // REMOVED: groupStore, cookielessManager, groupTypeManager from deps/config
    return builder
        .messageAware((b) =>
            b
                .sequentially((b) =>
                    createTestingPreTeamPreprocessingSubpipeline(b, {
                        teamManager: deps.teamManager,
                    })
                )
                .filterMap(addTeamToContext, (b) =>
                    b
                        .teamAware((b) =>
                            createTestingPostTeamPreprocessingSubpipeline(b, {
                                personsStore,
                                personsPrefetchEnabled,
                            })
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
