import { TeamManager } from '../../utils/team-manager'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { createClientWarningsConsumer } from './consumer'
import * as pipelineModule from './pipeline'

jest.mock('./pipeline')

describe('createClientWarningsConsumer', () => {
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
        outputs: IngestionOutputs<IngestionWarningsOutput | DlqOutput>
        teamManager: TeamManager
    } {
        const outputs = {
            checkTopics: jest.fn().mockResolvedValue([]),
        } as unknown as IngestionOutputs<IngestionWarningsOutput | DlqOutput>
        const teamManager = {} as TeamManager
        return { outputs, teamManager }
    }

    beforeEach(() => {
        ;(pipelineModule.createClientWarningsPipeline as jest.Mock) = jest.fn().mockReturnValue({
            feed: jest.fn(),
            next: jest.fn(),
        })
    })

    it('returns a CommonIngestionConsumer', () => {
        const consumer = createClientWarningsConsumer(makeConfig(), makeDeps())
        expect(consumer).toBeInstanceOf(CommonIngestionConsumer)
    })

    it('passes outputs, teamManager, and promiseScheduler to the pipeline factory', () => {
        const deps = makeDeps()
        createClientWarningsConsumer(makeConfig(), deps)

        expect(pipelineModule.createClientWarningsPipeline).toHaveBeenCalledTimes(1)
        const call = (pipelineModule.createClientWarningsPipeline as jest.Mock).mock.calls[0][0]
        expect(call.outputs).toBe(deps.outputs)
        expect(call.teamManager).toBe(deps.teamManager)
        expect(call.promiseScheduler).toBeDefined()
    })

    it('exposes a service descriptor with the topic-derived id', () => {
        const consumer = createClientWarningsConsumer(makeConfig(), makeDeps(), { topic: 'client_warnings' })
        expect(consumer.service.id).toBe('ingestion-consumer-client_warnings')
    })

    it('forwards group id and topic overrides', () => {
        const consumer = createClientWarningsConsumer(makeConfig(), makeDeps(), {
            groupId: 'custom_group',
            topic: 'custom_topic',
        })
        expect(consumer.service.id).toBe('ingestion-consumer-custom_topic')
    })
})
