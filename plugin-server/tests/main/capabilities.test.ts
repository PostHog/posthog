import Piscina from '@posthog/piscina'

import { KafkaQueue } from '../../src/main/ingestion-queues/kafka-queue'
import { startQueues } from '../../src/main/ingestion-queues/queue'
import { Hub, LogLevel } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'

jest.mock('../../src/main/ingestion-queues/kafka-queue')

describe('queue', () => {
    describe('capabilities', () => {
        let hub: Hub
        let piscina: Piscina
        let closeHub: () => Promise<void>

        beforeEach(async () => {
            ;[hub, closeHub] = await createHub({
                LOG_LEVEL: LogLevel.Warn,
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
            hub.capabilities.processAsyncHandlers = false

            const queues = await startQueues(hub, piscina)

            expect(queues).toEqual({
                ingestion: null,
            })
        })
    })
})
