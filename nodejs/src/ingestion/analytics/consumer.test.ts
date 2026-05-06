import { TeamManager } from '../../utils/team-manager'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { DlqOutput, EventOutput, IngestionWarningsOutput } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { createAnalyticsConsumer } from './consumer'
import * as pipelineModule from './pipeline'

jest.mock('./pipeline')

describe('createAnalyticsConsumer', () => {
    function makeConfig(): CommonIngestionConsumerConfig {
        return {
            INGESTION_CONSUMER_GROUP_ID: 'analytics_group',
            INGESTION_CONSUMER_CONSUME_TOPIC: 'events',
            INGESTION_PIPELINE: 'analytics',
            INGESTION_LANE: 'main',
            KAFKA_BATCH_START_LOGGING_ENABLED: false,
        }
    }

    function makeDeps(): {
        outputs: IngestionOutputs<EventOutput | DlqOutput | IngestionWarningsOutput>
        teamManager: TeamManager
    } {
        const outputs = {
            checkTopics: jest.fn().mockResolvedValue([]),
        } as unknown as IngestionOutputs<EventOutput | DlqOutput | IngestionWarningsOutput>
        const teamManager = {
            start: jest.fn().mockResolvedValue(undefined),
            stop: jest.fn().mockResolvedValue(undefined),
        } as unknown as TeamManager
        return { outputs, teamManager }
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

    it('passes outputs, teamManager, scheduler, and groupId to the pipeline factory', () => {
        const deps = makeDeps()
        createAnalyticsConsumer(makeConfig(), deps)

        expect(pipelineModule.createAnalyticsPipeline).toHaveBeenCalledTimes(1)
        const call = (pipelineModule.createAnalyticsPipeline as jest.Mock).mock.calls[0][0]
        expect(call.outputs).toBe(deps.outputs)
        expect(call.teamManager).toBe(deps.teamManager)
        expect(call.promiseScheduler).toBeDefined()
        expect(call.groupId).toBe('analytics_group')
    })

    it('exposes a service descriptor whose id derives from the configured topic', () => {
        const consumer = createAnalyticsConsumer(makeConfig(), makeDeps())
        expect(consumer.service.id).toBe('ingestion-consumer-events')
    })
})
