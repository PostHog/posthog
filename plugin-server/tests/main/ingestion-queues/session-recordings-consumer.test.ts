import { KafkaJSError } from 'kafkajs'
import { Pool } from 'pg'

import { eachBatch } from '../../../src/main/ingestion-queues/session-recordings-consumer'
import { DB } from '../../../src/utils/db/db'
import { DependencyUnavailableError } from '../../../src/utils/db/error'
import { KafkaProducerWrapper } from '../../../src/utils/db/kafka-producer-wrapper'
import { TeamManager } from '../../../src/worker/ingestion/team-manager'

describe('session-recordings-consumer', () => {
    let producer
    let producerWrapper: KafkaProducerWrapper
    let db: DB
    let teamManager: TeamManager
    let eachBachWithDependencies: any

    beforeEach(() => {
        jest.useFakeTimers()

        producer = {
            sendBatch: jest.fn(),
        } as any
        producerWrapper = new KafkaProducerWrapper(producer, undefined, { KAFKA_FLUSH_FREQUENCY_MS: 0 } as any)
        db = {
            postgres: new Pool(),
        } as DB
        teamManager = new TeamManager(db)
        eachBachWithDependencies = eachBatch({ producer: producerWrapper, teamManager })
    })

    afterEach(() => {
        jest.useRealTimers()
        jest.clearAllMocks()
    })

    test('eachBatch throws on recoverable KafkaJS errors', async () => {
        const error = new KafkaJSError('test', { retriable: true })
        producer.sendBatch.mockRejectedValue(error)
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
        producer.sendBatch.mockRejectedValue(error)
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
