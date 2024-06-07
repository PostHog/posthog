import { CdpProcessedEventsConsumer } from '../../src/cdp/cdp-processed-events-consumer'
import { defaultConfig } from '../../src/config/config'
import { Hub, PluginsServerConfig, Team } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { getFirstTeam, resetTestDatabase } from '../helpers/sql'

const config: PluginsServerConfig = {
    ...defaultConfig,
}

const mockConsumer = {
    on: jest.fn(),
    commitSync: jest.fn(),
    commit: jest.fn(),
    queryWatermarkOffsets: jest.fn(),
    committed: jest.fn(),
    assignments: jest.fn(),
    isConnected: jest.fn(() => true),
    getMetadata: jest.fn(),
}

jest.mock('../../../../src/kafka/batch-consumer', () => {
    return {
        startBatchConsumer: jest.fn(() =>
            Promise.resolve({
                join: () => ({
                    finally: jest.fn(),
                }),
                stop: jest.fn(),
                consumer: mockConsumer,
            })
        ),
    }
})

jest.setTimeout(1000)

describe.each([[true], [false]])('ingester with consumeOverflow=%p', (consumeOverflow) => {
    let processor: CdpProcessedEventsConsumer

    let hub: Hub
    let closeHub: () => Promise<void>
    let team: Team
    let teamToken = ''

    beforeAll(async () => {
        await resetTestDatabase()
    })

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
        team = await getFirstTeam(hub)
        teamToken = team.api_token

        processor = new CdpProcessedEventsConsumer(config, hub.postgres, consumeOverflow)
        await processor.start()
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await closeHub()
    })

    afterAll(() => {
        jest.useRealTimers()
    })
})
