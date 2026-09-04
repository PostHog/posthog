import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { LiveUserCountStats, liveUserCountLogic } from './liveUserCountLogic'

type StatsResponse = LiveUserCountStats | { error: string }

describe('liveUserCountLogic', () => {
    let logic: ReturnType<typeof liveUserCountLogic.build>
    let statsResponse: StatsResponse

    beforeEach(async () => {
        useMocks({ get: { '/api/environments/@current/': MOCK_DEFAULT_TEAM } })
        initKeaTests()
        global.fetch = jest.fn(async () => ({ json: async () => statsResponse })) as unknown as typeof fetch
        teamLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()
        logic = liveUserCountLogic({ pollIntervalMs: 30000 })
    })

    afterEach(() => {
        logic.unmount()
    })

    // Mounting starts the first poll, so the response must be in place before it.
    function start(response: StatsResponse): void {
        statsResponse = response
        logic.mount()
    }

    async function poll(response: StatsResponse): Promise<void> {
        statsResponse = response
        logic.actions.pollStats()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('reports a zero count as zero, not as missing data', async () => {
        start({ users_on_product: 0, active_recordings: 0 })
        await expectLogic(logic).toFinishAllListeners()

        expectLogic(logic).toMatchValues({ activeRecordings: 0, liveUserCount: 0 })
    })

    it('keeps the last known counts when a poll returns no data', async () => {
        start({ users_on_product: 5, active_recordings: 3 })
        await expectLogic(logic).toFinishAllListeners()
        await poll({ error: 'no stats' })

        expectLogic(logic).toMatchValues({ activeRecordings: 3, liveUserCount: 5 })
    })

    it('reports no data before the first poll resolves', () => {
        start({ users_on_product: 5, active_recordings: 3 })

        expectLogic(logic).toMatchValues({ activeRecordings: null, liveUserCount: null })
    })
})
