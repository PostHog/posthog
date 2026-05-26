import { RedisPool } from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
import { TeamManagerLifecycle } from '../../utils/team-manager'
import { CommonIngestionConsumer } from '../common/common-ingestion-consumer'
import { ProducerName } from '../common/outputs'
import { newLifecycleBuilder } from '../common/service-registry'
import { IngestionOutputsConfig } from '../config'
import { KafkaProducerRegistry } from '../outputs/kafka-producer-registry'
import { ClientWarningsConsumerConfig, ClientWarningsSharedLifecycle, createClientWarningsConsumer } from './consumer'
import * as pipelineModule from './pipeline'

jest.mock('./pipeline')

describe('createClientWarningsConsumer', () => {
    function makeConfig(): ClientWarningsConsumerConfig {
        return {
            INGESTION_CONSUMER_GROUP_ID: 'g',
            INGESTION_CONSUMER_CONSUME_TOPIC: 't',
            INGESTION_PIPELINE: 'analytics',
            INGESTION_LANE: 'main',
            KAFKA_BATCH_START_LOGGING_ENABLED: false,
            ...({} as IngestionOutputsConfig),
        }
    }

    function makeSharedLifecycle(): ClientWarningsSharedLifecycle {
        // The consumer factory chains off this lifecycle but doesn't start
        // it (start happens inside `consumer.start()`), so the shape only
        // has to be type-correct — the Managers' bodies don't run.
        return newLifecycleBuilder()
            .register('postgres', {
                start: () => Promise.resolve({ service: {} as PostgresRouter, stop: () => Promise.resolve() }),
            })
            .register('redisPool', {
                start: () => Promise.resolve({ service: {} as RedisPool, stop: () => Promise.resolve() }),
            })
            .register('teamManager', new TeamManagerLifecycle({} as PostgresRouter))
            .register('producerRegistry', {
                start: () =>
                    Promise.resolve({
                        service: {} as KafkaProducerRegistry<ProducerName>,
                        stop: () => Promise.resolve(),
                    }),
            })
            .register('staticDropEventTokens', {
                start: () => Promise.resolve({ service: [] as string[], stop: () => Promise.resolve() }),
            })
            .build('shared-test')
    }

    beforeEach(() => {
        ;(pipelineModule.createClientWarningsPipeline as jest.Mock) = jest.fn().mockReturnValue({
            feed: jest.fn(),
            next: jest.fn(),
        })
    })

    it('returns a CommonIngestionConsumer', () => {
        const consumer = createClientWarningsConsumer(makeConfig(), makeSharedLifecycle())
        expect(consumer).toBeInstanceOf(CommonIngestionConsumer)
    })

    it('defers pipeline construction until start time', () => {
        createClientWarningsConsumer(makeConfig(), makeSharedLifecycle())

        // The pipeline factory runs inside `consumer.start()`, after the
        // lifecycle's services come up — not at consumer construction time.
        expect(pipelineModule.createClientWarningsPipeline).not.toHaveBeenCalled()
    })

    it('exposes a service descriptor whose id derives from the configured topic', () => {
        const consumer = createClientWarningsConsumer(
            { ...makeConfig(), INGESTION_CONSUMER_CONSUME_TOPIC: 'client_warnings' },
            makeSharedLifecycle()
        )
        expect(consumer.service.id).toBe('ingestion-consumer-client_warnings')
    })
})
