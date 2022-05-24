import Piscina from '@posthog/piscina'

import { KafkaQueue } from '../src/main/ingestion-queues/kafka-queue'
import { startQueues } from '../src/main/ingestion-queues/queue'
import { Hub, LogLevel } from '../src/types'
import { createHub } from '../src/utils/db/hub'

jest.setTimeout(60000) // 60 sec timeout
jest.mock('../src/main/ingestion-queues/kafka-queue')
jest.mock('../src/utils/status')
jest.mock('../src/main/ingestion-queues/batch-processing/each-batch-ingestion')

describe('queue', () => {
    describe('capabilities', () => {
        let hub: Hub
        let piscina: Piscina
        let closeHub: () => Promise<void>

        beforeEach(async () => {
            ;[hub, closeHub] = await createHub({
                LOG_LEVEL: LogLevel.Warn,
                KAFKA_ENABLED: true,
                KAFKA_HOSTS: process.env.KAFKA_HOSTS || 'kafka:9092',
            })
            piscina = { run: jest.fn() } as any
        })

        afterEach(async () => {
            await closeHub()
        })

        it('starts ingestion queue by default', async () => {
            const queues = await startQueues(hub, piscina)

            expect(queues).toEqual({
                ingestion: expect.any(KafkaQueue),
            })
        })

        it('handles ingestion being turned off', async () => {
            hub.capabilities.ingestion = false

            const queues = await startQueues(hub, piscina)

            expect(queues).toEqual({
                ingestion: null,
            })
        })
    })
})
