import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '../../utils/event-schema-enforcement-manager'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { BatchWritingPersonsStore } from '../../worker/ingestion/persons/batch-writing-person-store'
import { CommonIngestionConsumer } from '../common/common-ingestion-consumer'
import { EventFilterManager } from '../common/event-filters'
import { AppMetricsOutput, DlqOutput, GroupsOutput, IngestionWarningsOutput, OverflowOutput } from '../common/outputs'
import { CookielessManager } from '../cookieless/cookieless-manager'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { TopHog } from '../tophog'
import { AnalyticsConsumerDeps, AnalyticsConsumerFullConfig, createAnalyticsConsumer } from './consumer'
import {
    AiEventOutput,
    AsyncOutput,
    EventOutput,
    HeatmapsOutput,
    PersonDistinctIdsOutput,
    PersonsOutput,
} from './outputs'
import * as pipelineModule from './pipeline'

jest.mock('./pipeline')

function makeNoopService(): { start: jest.Mock; stop: jest.Mock } {
    return {
        start: jest.fn().mockResolvedValue(undefined),
        stop: jest.fn().mockResolvedValue(undefined),
    }
}

describe('createAnalyticsConsumer', () => {
    function makeConfig(): AnalyticsConsumerFullConfig {
        return {
            INGESTION_CONSUMER_GROUP_ID: 'analytics_group',
            INGESTION_CONSUMER_CONSUME_TOPIC: 'events',
            INGESTION_PIPELINE: 'analytics',
            INGESTION_LANE: 'main',
            KAFKA_BATCH_START_LOGGING_ENABLED: false,
            EVENT_SCHEMA_ENFORCEMENT_ENABLED: false,
            INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY: false,
            PERSONS_PREFETCH_ENABLED: false,
            SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: false,
            PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: 100,
            PERSON_MERGE_ASYNC_ENABLED: false,
            PERSON_MERGE_SYNC_BATCH_SIZE: 10,
            PERSON_JSONB_SIZE_ESTIMATE_ENABLE: 0,
            PERSON_PROPERTIES_UPDATE_ALL: false,
            CDP_HOG_WATCHER_SAMPLE_RATE: 0,
        }
    }

    function makeDeps(): AnalyticsConsumerDeps {
        const outputs = {
            checkTopics: jest.fn().mockResolvedValue([]),
        } as unknown as IngestionOutputs<
            | EventOutput
            | AiEventOutput
            | HeatmapsOutput
            | IngestionWarningsOutput
            | DlqOutput
            | OverflowOutput
            | AsyncOutput
            | GroupsOutput
            | PersonsOutput
            | PersonDistinctIdsOutput
            | AppMetricsOutput
        >
        return {
            outputs,
            teamManager: makeNoopService() as unknown as TeamManager,
            eventFilterManager: makeNoopService() as unknown as EventFilterManager,
            eventIngestionRestrictionManager: makeNoopService() as unknown as EventIngestionRestrictionManager,
            eventSchemaEnforcementManager: makeNoopService() as unknown as EventSchemaEnforcementManager,
            cookielessManager: makeNoopService() as unknown as CookielessManager,
            personsStore: makeNoopService() as unknown as BatchWritingPersonsStore,
            groupStore: makeNoopService() as unknown as BatchWritingGroupStore,
            groupTypeManager: makeNoopService() as unknown as GroupTypeManager,
            hogTransformer: makeNoopService() as unknown as HogTransformerService,
            topHog: makeNoopService() as unknown as TopHog,
            overflowEnabled: false,
        }
    }

    beforeEach(() => {
        ;(pipelineModule.createAnalyticsPipeline as jest.Mock) = jest.fn().mockReturnValue({
            feed: jest.fn(),
            next: jest.fn(),
        })
    })

    it('returns a CommonIngestionConsumer', () => {
        const consumer = createAnalyticsConsumer(makeConfig(), makeDeps())
        expect(consumer).toBeInstanceOf(CommonIngestionConsumer)
    })

    it('passes services and config to the pipeline factory via spread', () => {
        const deps = makeDeps()
        createAnalyticsConsumer(makeConfig(), deps)

        expect(pipelineModule.createAnalyticsPipeline).toHaveBeenCalledTimes(1)
        const [pipelineConfig, pipelineDeps] = (pipelineModule.createAnalyticsPipeline as jest.Mock).mock.calls[0]
        expect(pipelineDeps.teamManager).toBe(deps.teamManager)
        expect(pipelineDeps.topHog).toBe(deps.topHog)
        expect(pipelineDeps.hogTransformer).toBe(deps.hogTransformer)
        expect(pipelineDeps.personsStore).toBe(deps.personsStore)
        expect(pipelineDeps.groupStore).toBe(deps.groupStore)
        expect(pipelineDeps.promiseScheduler).toBeDefined()
        expect(pipelineConfig.groupId).toBe('analytics_group')
    })

    it('exposes a service descriptor whose id derives from the configured topic', () => {
        const consumer = createAnalyticsConsumer(makeConfig(), makeDeps())
        expect(consumer.service.id).toBe('ingestion-consumer-events')
    })
})
