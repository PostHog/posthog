import { mkdirSync, rmSync } from 'node:fs'
import path from 'path'

import { waitForExpect } from '../../../../functional_tests/expectations'
import { defaultConfig } from '../../../../src/config/config'
import { SessionRecordingIngesterV2 } from '../../../../src/main/ingestion-queues/session-recording/session-recordings-consumer-v2'
import { Hub, PluginsServerConfig } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { UUIDT } from '../../../../src/utils/utils'
import { createIncomingRecordingMessage } from './fixtures'

function assertIngesterHasExpectedPartitions(ingester: SessionRecordingIngesterV2, expectedPartitions: number[]) {
    const partitions: Set<number> = new Set()
    Object.values(ingester.sessions).forEach((session) => {
        partitions.add(session.partition)
    })
    expect(Array.from(partitions)).toEqual(expectedPartitions)
}

describe('ingester rebalancing tests', () => {
    const config: PluginsServerConfig = {
        ...defaultConfig,
        SESSION_RECORDING_LOCAL_DIRECTORY: '.tmp/test-session-recordings',
    }

    let ingesterOne: SessionRecordingIngesterV2
    let ingesterTwo: SessionRecordingIngesterV2

    let hub: Hub
    let closeHub: () => Promise<void>

    beforeAll(() => {
        mkdirSync(path.join(config.SESSION_RECORDING_LOCAL_DIRECTORY, 'session-buffer-files'), { recursive: true })
    })

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
    })

    afterEach(async () => {
        await ingesterOne?.stop()
        await ingesterTwo?.stop()
        await closeHub()
    })

    afterAll(() => {
        rmSync(config.SESSION_RECORDING_LOCAL_DIRECTORY, { recursive: true, force: true })
    })

    it('rebalances partitions safely from one to two consumers', async () => {
        ingesterOne = new SessionRecordingIngesterV2(config, hub.postgres, hub.objectStorage, hub.redisPool)

        await ingesterOne.start()
        await ingesterOne.consume(createIncomingRecordingMessage({ session_id: new UUIDT().toString() }))
        await ingesterOne.consume(createIncomingRecordingMessage({ session_id: new UUIDT().toString() }))

        await waitForExpect(() => {
            assertIngesterHasExpectedPartitions(ingesterOne, [1])
        })

        ingesterTwo = new SessionRecordingIngesterV2(config, hub.postgres, hub.objectStorage, hub.redisPool)
        await ingesterTwo.start()

        await waitForExpect(() => {
            // because the rebalancing strategy is cooperative sticky the partition stays on the same ingester
            assertIngesterHasExpectedPartitions(ingesterOne, [1])

            // only one partition so nothing for the new consumer to do
            assertIngesterHasExpectedPartitions(ingesterTwo, [])
        })
    })
})
