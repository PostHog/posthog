import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { TeamManagerComponent } from '~/common/utils/team-manager'
import { ProducerName } from '~/ingestion/common/producers'
import { newScope } from '~/ingestion/common/scopes'
import { IngestionOutputsConfig } from '~/ingestion/config'
import { RedisPool } from '~/types'

import { ClientWarningsConsumerConfig, ClientWarningsSharedScope, createClientWarningsConsumer } from './consumer'
import * as pipelineModule from './pipeline'

jest.mock('./pipeline')

describe('createClientWarningsConsumer', () => {
    function makeConfig(): ClientWarningsConsumerConfig {
        return {
            INGESTION_CONSUMER_GROUP_ID: 'g',
            INGESTION_CONSUMER_CONSUME_TOPIC: 't',
            INGESTION_PIPELINE: 'clientwarnings',
            INGESTION_LANE: 'main',
            KAFKA_BATCH_START_LOGGING_ENABLED: false,
            DROP_EVENTS_BY_TOKEN_DISTINCT_ID: '',
            ...({} as IngestionOutputsConfig),
        }
    }

    function makeSharedScope(): ClientWarningsSharedScope {
        // The consumer factory extends this scope but doesn't start it
        // (start happens at the caller), so the shape only has to be
        // type-correct — the components' bodies don't run.
        return newScope('shared-test', (b) =>
            b
                .add('postgres', {
                    start: () => Promise.resolve({ value: {} as PostgresRouter, stop: () => Promise.resolve() }),
                })
                .add('redisPool', {
                    start: () => Promise.resolve({ value: {} as RedisPool, stop: () => Promise.resolve() }),
                })
                .add('teamManager', new TeamManagerComponent({} as PostgresRouter))
                .add('producerRegistry', {
                    start: () =>
                        Promise.resolve({
                            value: {} as KafkaProducerRegistry<ProducerName>,
                            stop: () => Promise.resolve(),
                        }),
                })
        )
    }

    beforeEach(() => {
        ;(pipelineModule.createClientWarningsPipeline as jest.Mock) = jest.fn().mockReturnValue({
            feed: jest.fn(),
            next: jest.fn(),
        })
    })

    it('defers pipeline construction until scope.start()', () => {
        createClientWarningsConsumer(makeConfig(), makeSharedScope())

        // The pipeline factory runs inside the extend callback at start
        // time, after the scope's services come up — not at consumer
        // construction time.
        expect(pipelineModule.createClientWarningsPipeline).not.toHaveBeenCalled()
    })
})
