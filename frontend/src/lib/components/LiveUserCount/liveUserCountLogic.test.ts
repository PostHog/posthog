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
    let statsStatus: number
    let consoleError: jest.SpyInstance

    beforeEach(async () => {
        useMocks({ get: { '/api/environments/@current/': MOCK_DEFAULT_TEAM } })
        initKeaTests()
        statsStatus = 200
        consoleError = jest.spyOn(console, 'error').mockImplementation(() => {})
        global.fetch = jest.fn(async () => ({
            ok: statsStatus >= 200 && statsStatus < 300,
            status: statsStatus,
            json: async () => statsResponse,
        })) as unknown as typeof fetch
        teamLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()
        logic = liveUserCountLogic({ pollIntervalMs: 30000 })
    })

    afterEach(() => {
        logic.unmount()
        consoleError.mockRestore()
    })

    // Mounting starts the first poll, so the response must be in place before it.
    function start(response: StatsResponse): void {
        statsResponse = response
        logic.mount()
    }

    async function poll(response: StatsResponse, status: number = 200): Promise<void> {
        statsResponse = response
        statsStatus = status
        logic.actions.pollStats()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('reports a zero count as zero, not as missing data', async () => {
        start({ users_on_product: 0, active_recordings: 0 })
        await expectLogic(logic).toFinishAllListeners()

        expectLogic(logic).toMatchValues({ activeRecordings: 0, liveUserCount: 0 })
    })

    it.each([
        { situation: 'a poll returns no data', status: 200, body: { error: 'no stats' }, reports: 0 },
        { situation: 'a poll fails', status: 401, body: { error: 'wrong token claims' }, reports: 1 },
    ])('keeps the last known counts when $situation', async ({ status, body, reports }) => {
        start({ users_on_product: 5, active_recordings: 3 })
        await expectLogic(logic).toFinishAllListeners()
        consoleError.mockClear()

        await poll(body, status)

        expectLogic(logic).toMatchValues({ activeRecordings: 3, liveUserCount: 5 })
        expect(consoleError).toHaveBeenCalledTimes(reports)
    })

    it('reports no data before the first poll resolves', () => {
        start({ users_on_product: 5, active_recordings: 3 })

        expectLogic(logic).toMatchValues({ activeRecordings: null, liveUserCount: null })
    })
})
