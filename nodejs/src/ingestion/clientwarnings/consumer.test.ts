import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { TeamManagerHandle } from '../../utils/team-manager'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { EventFilterManager } from '../common/event-filters'
import { AppMetricsOutput, DlqOutput, IngestionWarningsOutput } from '../common/outputs'
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
        outputs: IngestionOutputs<IngestionWarningsOutput | DlqOutput | AppMetricsOutput>
        teamManager: TeamManagerHandle
        eventIngestionRestrictionManager: EventIngestionRestrictionManager
        eventFilterManager: EventFilterManager
    } {
        const outputs = {
            checkTopics: jest.fn().mockResolvedValue([]),
        } as unknown as IngestionOutputs<IngestionWarningsOutput | DlqOutput | AppMetricsOutput>
        return {
            outputs,
            teamManager: {} as TeamManagerHandle,
            eventIngestionRestrictionManager: {} as EventIngestionRestrictionManager,
            eventFilterManager: {} as EventFilterManager,
        }
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

    it('defers pipeline construction until start time', () => {
        createClientWarningsConsumer(makeConfig(), makeDeps())

        // The pipeline factory runs inside `consumer.start()`, after the
        // lifecycle's services come up — not at consumer construction time.
        expect(pipelineModule.createClientWarningsPipeline).not.toHaveBeenCalled()
    })

    it('exposes a service descriptor whose id derives from the configured topic', () => {
        const consumer = createClientWarningsConsumer(
            { ...makeConfig(), INGESTION_CONSUMER_CONSUME_TOPIC: 'client_warnings' },
            makeDeps()
        )
        expect(consumer.service.id).toBe('ingestion-consumer-client_warnings')
    })
})
