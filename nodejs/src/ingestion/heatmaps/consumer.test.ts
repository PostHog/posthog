import { TeamManager } from '../../utils/team-manager'
import { HeatmapsOutput } from '../analytics/outputs'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { createHeatmapsConsumer } from './consumer'
import * as pipelineModule from './pipeline'

jest.mock('./pipeline')

describe('createHeatmapsConsumer', () => {
    function makeConfig(): CommonIngestionConsumerConfig {
        return {
            INGESTION_CONSUMER_GROUP_ID: 'g',
            INGESTION_CONSUMER_CONSUME_TOPIC: 't',
            INGESTION_PIPELINE: 'analytics',
            INGESTION_LANE: 'main',
            KAFKA_BATCH_START_LOGGING_ENABLED: false,
        }
    }

    function makeDeps(): {
        outputs: IngestionOutputs<HeatmapsOutput | DlqOutput | IngestionWarningsOutput>
        teamManager: TeamManager
    } {
        const outputs = {
            checkTopics: jest.fn().mockResolvedValue([]),
        } as unknown as IngestionOutputs<HeatmapsOutput | DlqOutput | IngestionWarningsOutput>
        const teamManager = {
            start: jest.fn().mockResolvedValue(undefined),
            stop: jest.fn().mockResolvedValue(undefined),
        } as unknown as TeamManager
        return { outputs, teamManager }
    }

    beforeEach(() => {
        ;(pipelineModule.createHeatmapsPipeline as jest.Mock) = jest.fn().mockReturnValue({
            feed: jest.fn(),
            next: jest.fn(),
        })
    })

    it('returns a CommonIngestionConsumer', () => {
        const consumer = createHeatmapsConsumer(makeConfig(), makeDeps())
        expect(consumer).toBeInstanceOf(CommonIngestionConsumer)
    })

    it('passes outputs, teamManager, and promiseScheduler to the pipeline factory', () => {
        const deps = makeDeps()
        createHeatmapsConsumer(makeConfig(), deps)

        expect(pipelineModule.createHeatmapsPipeline).toHaveBeenCalledTimes(1)
        const call = (pipelineModule.createHeatmapsPipeline as jest.Mock).mock.calls[0][0]
        expect(call.outputs).toBe(deps.outputs)
        expect(call.teamManager).toBe(deps.teamManager)
        expect(call.promiseScheduler).toBeDefined()
    })

    it('exposes a service descriptor whose id derives from the configured topic', () => {
        const consumer = createHeatmapsConsumer(
            { ...makeConfig(), INGESTION_CONSUMER_CONSUME_TOPIC: 'heatmaps' },
            makeDeps()
        )
        expect(consumer.service.id).toBe('ingestion-consumer-heatmaps')
    })
})
