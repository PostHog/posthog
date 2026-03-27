import { Message } from 'node-rdkafka'

import { Team } from '../../types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { BatchPipelineBuilder } from '../pipelines/builders/batch-pipeline-builders'
import { OkResultWithContext } from '../pipelines/pipeline.interface'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { ok } from '../pipelines/results'
import { EventOutput, HeatmapsOutput } from './outputs'
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
    groupId: string
    outputs: IngestionOutputs<EventOutput | HeatmapsOutput | IngestionWarningsOutput | DlqOutput>
}

export interface TestingJoinedIngestionPipelineDeps {
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
    const { groupId, outputs } = config

    const { promiseScheduler } = deps

    const pipelineConfig: PipelineConfig = {
        outputs,
        promiseScheduler,
    }

    const perEventConfig: TestingPerDistinctIdPipelineConfig = {
        outputs,
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
                    createTestingPreTeamPreprocessingSubpipeline(b, {
                        teamManager: deps.teamManager,
                    })
                )
                .filterMap(addTeamToContext, (b) =>
                    b
                        .teamAware((b) =>
                            createTestingPostTeamPreprocessingSubpipeline(b)
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
                        .handleIngestionWarnings(outputs)
                )
        )
        .handleResults(pipelineConfig)
        .handleSideEffects(promiseScheduler, { await: false })
}
