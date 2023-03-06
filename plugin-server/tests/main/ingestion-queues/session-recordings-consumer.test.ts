import { Kafka, KafkaJSError, Partitioners, Producer } from 'kafkajs'
import Broker from 'kafkajs/src/broker'

import { defaultConfig } from '../../../src/config/config'
import { eachBatch } from '../../../src/main/ingestion-queues/session-recordings-consumer'
import { DB } from '../../../src/utils/db/db'
import { DependencyUnavailableError } from '../../../src/utils/db/error'
import { KafkaProducerWrapper } from '../../../src/utils/db/kafka-producer-wrapper'
import { createPostgresPool } from '../../../src/utils/utils'
import { TeamManager } from '../../../src/worker/ingestion/team-manager'
import { createOrganization, createTeam } from '../../helpers/sql'

describe('session-recordings-consumer', () => {
    // NOTE: at the time of adding this comment, the test only checks the case
    // that we error at the time of producing to the ClickHouse ingestion Kafka
    // topic. There are also other cases that can fail which we should also
    // test.

    let mockProduce: jest.SpyInstance
    let kafka: Kafka
    let producer: Producer
    let producerWrapper: KafkaProducerWrapper
    let db: DB
    let teamManager: TeamManager
    let eachBachWithDependencies: any

    beforeEach(async () => {
        kafka = new Kafka({ brokers: ['localhost:9092'] })
        producer = kafka.producer({ retry: { retries: 0 }, createPartitioner: Partitioners.LegacyPartitioner })
        await producer.connect()

        // To ensure we are catching and retrying on the correct error, we make
        // sure to mock deep into the KafkaJS internals, otherwise we can get
        // into inplaced confidence that we have covered this critical path.
        mockProduce = jest.spyOn(Broker.prototype, 'produce')
        producerWrapper = new KafkaProducerWrapper(producer, undefined, {
            KAFKA_FLUSH_FREQUENCY_MS: 0,
        } as any)
        db = {
            postgres: createPostgresPool(defaultConfig.DATABASE_URL),
        } as DB
        teamManager = new TeamManager(db.postgres, {} as any)
        eachBachWithDependencies = eachBatch({ groupId: 'test', producer: producerWrapper, teamManager })
    })

    afterEach(async () => {
        await producer.disconnect()
        jest.clearAllMocks()
    })

    test('eachBatch throws on recoverable KafkaJS errors', async () => {
        const organizationId = await createOrganization(db.postgres)
        const teamId = await createTeam(db.postgres, organizationId)
        const error = new KafkaJSError('test', { retriable: true })
        mockProduce.mockRejectedValueOnce(error)
        await expect(
            eachBachWithDependencies({
                batch: {
                    topic: 'test',
                    messages: [
                        {
                            key: 'test',
                            value: JSON.stringify({ team_id: teamId, data: JSON.stringify({ event: '$snapshot' }) }),
                        },
                    ],
                } as any,
                heartbeat: jest.fn(),
            })
        ).rejects.toEqual(new DependencyUnavailableError('KafkaJSError', 'Kafka', error))

        // Should _not_ have retried or sent to DLQ.
        expect(mockProduce).toHaveBeenCalledTimes(1)
    })

    test('eachBatch emits to DLQ and returns on unrecoverable KafkaJS errors', async () => {
        const organizationId = await createOrganization(db.postgres)
        const teamId = await createTeam(db.postgres, organizationId)
        const error = new KafkaJSError('test', { retriable: false })
        mockProduce.mockRejectedValueOnce(error)
        await eachBachWithDependencies({
            batch: {
                topic: 'test',
                messages: [
                    {
                        key: 'test',
                        value: JSON.stringify({ team_id: teamId, data: JSON.stringify({ event: '$snapshot' }) }),
                    },
                ],
            } as any,
            heartbeat: jest.fn(),
        })

        // Should have send to the DLQ.
        expect(mockProduce).toHaveBeenCalledTimes(2)
    })
})
