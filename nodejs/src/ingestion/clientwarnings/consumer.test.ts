import { TeamManagerHandle } from '../../utils/team-manager'
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
        teamManager: TeamManagerHandle
    } {
        const outputs = {
            checkTopics: jest.fn().mockResolvedValue([]),
        } as unknown as IngestionOutputs<IngestionWarningsOutput | DlqOutput>
        const teamManager = {} as TeamManagerHandle
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

    it('exposes a service descriptor whose id derives from the configured topic', () => {
        const consumer = createClientWarningsConsumer(
            { ...makeConfig(), INGESTION_CONSUMER_CONSUME_TOPIC: 'client_warnings' },
            makeDeps()
        )
        expect(consumer.service.id).toBe('ingestion-consumer-client_warnings')
    })
})
