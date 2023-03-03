import { Kafka, KafkaJSError, Producer } from 'kafkajs'
import Cluster from 'kafkajs/src/cluster'
import { Pool } from 'pg'

import { eachBatch } from '../../../src/main/ingestion-queues/session-recordings-consumer'
import { DB } from '../../../src/utils/db/db'
import { DependencyUnavailableError } from '../../../src/utils/db/error'
import { KafkaProducerWrapper } from '../../../src/utils/db/kafka-producer-wrapper'
import { TeamManager } from '../../../src/worker/ingestion/team-manager'

describe('session-recordings-consumer', () => {
    let mockRefreshMetadataIfNecessary: jest.SpyInstance
    let kafka: Kafka
    let producer: Producer
    let producerWrapper: KafkaProducerWrapper
    let db: DB
    let teamManager: TeamManager
    let eachBachWithDependencies: any

    beforeEach(async () => {
        jest.useFakeTimers()

        kafka = new Kafka({ brokers: ['localhost:9092'] })
        // To ensure we are catching and retrying on the correct error, we make
        // sure to mock deep into the KafkaJS internals, otherwise we can get
        // into inplaced confidence that we have covered this critical path.
        mockRefreshMetadataIfNecessary = jest.spyOn(Cluster.prototype, 'refreshMetadataIfNecessary')
        producer = kafka.producer({ retry: { retries: 0 } })
        await producer.connect()
        producerWrapper = new KafkaProducerWrapper(producer, undefined, {
            KAFKA_FLUSH_FREQUENCY_MS: 0,
        } as any)
        db = {
            postgres: new Pool(),
        } as DB
        teamManager = new TeamManager(db.postgres, {} as any)
        eachBachWithDependencies = eachBatch({ producer: producerWrapper, teamManager })
    })

    afterEach(async () => {
        await producer.disconnect()
        jest.useRealTimers()
        jest.clearAllMocks()
    })

    test('eachBatch throws on recoverable KafkaJS errors', async () => {
        const error = new KafkaJSError('test', { retriable: true })
        mockRefreshMetadataIfNecessary.mockImplementation(() => {
            throw error
        })
        await expect(
            eachBachWithDependencies({
                batch: {
                    topic: 'test',
                    messages: [
                        {
                            key: 'test',
                            value: JSON.stringify({ data: { event: '$snapshot' } }),
                        },
                    ],
                } as any,
                heartbeat: jest.fn(),
            })
        ).rejects.toEqual(new DependencyUnavailableError('KafkaJSError', 'Kafka', error))
    })

    test('eachBatch emits to DLQ and returns on unrecoverable KafkaJS errors', async () => {
        const error = new KafkaJSError('test', { retriable: false })
        mockRefreshMetadataIfNecessary.mockImplementation(() => {
            throw error
        })
        await eachBachWithDependencies({
            batch: {
                topic: 'test',
                messages: [
                    {
                        key: 'test',
                        value: JSON.stringify({ data: { event: '$snapshot' } }),
                    },
                ],
            } as any,
            heartbeat: jest.fn(),
        })
    })
})
