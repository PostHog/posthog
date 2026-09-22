import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { adBlockedCaptureLogic } from './adBlockedCaptureLogic'

describe('adBlockedCaptureLogic', () => {
    let logic: ReturnType<typeof adBlockedCaptureLogic.build>
    let queryResponse: [number, Record<string, any>]
    // The measurement is cached for 10 minutes outside the logic, so the clock only ever moves
    // forward here, and each case steps past that window to get a fresh query.
    let now = Date.now()
    let dateNowSpy: jest.SpyInstance

    beforeEach(() => {
        queryResponse = [200, { results: [] }]
        dateNowSpy = jest.spyOn(Date, 'now').mockImplementation(() => now)
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => queryResponse,
            },
        })
        initKeaTests()
        logic = adBlockedCaptureLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        dateNowSpy.mockRestore()
    })

    const measure = async (results: any[][]): Promise<void> => {
        queryResponse = [200, { results }]
        now += 1000 * 60 * 11
        logic.actions.loadAdBlockedCaptureStats()
        await expectLogic(logic).toDispatchActions(['loadAdBlockedCaptureStatsSuccess'])
    }

    it('reads the blocked and total session counts from the query', async () => {
        await measure([[120, 1000]])

        expect(logic.values.adBlockedCaptureStats).toEqual({ blockedSessions: 120, totalSessions: 1000 })
        expect(logic.values.adBlockedCaptureShare).toEqual(0.12)
    })

    // A scene change remounts the nav banner, so a cache that died with the logic would rerun a
    // week-wide scan on every navigation.
    it('keeps the measurement when the logic remounts inside the cache window', async () => {
        await measure([[120, 1000]])
        logic.unmount()
        logic = adBlockedCaptureLogic()
        logic.mount()

        queryResponse = [500, {}]
        logic.actions.loadAdBlockedCaptureStats()
        await expectLogic(logic).toDispatchActions(['loadAdBlockedCaptureStatsSuccess'])

        expect(logic.values.adBlockedCaptureStats).toEqual({ blockedSessions: 120, totalSessions: 1000 })
    })

    // The nudge fires on `hasSignificantAdBlockedCapture`, so each boundary here is a banner that
    // either nags an account losing nothing, or stays quiet for one losing a lot.
    it.each([
        { label: 'no measurement yet', results: [], share: null, significant: null },
        { label: 'no sessions at all', results: [[0, 0]], share: null, significant: false },
        { label: 'loss under the threshold', results: [[10, 1000]], share: 0.01, significant: false },
        { label: 'loss over the threshold', results: [[101, 1000]], share: 0.101, significant: true },
        { label: 'too few sessions to judge', results: [[10, 20]], share: 0.5, significant: false },
    ])('reports $label', async ({ results, share, significant }) => {
        await measure(results)

        expect(logic.values.adBlockedCaptureShare).toEqual(share)
        expect(logic.values.hasSignificantAdBlockedCapture).toEqual(significant)
    })

    it('leaves the measurement unknown when the query fails', async () => {
        queryResponse = [500, {}]
        now += 1000 * 60 * 11
        logic.actions.loadAdBlockedCaptureStats()

        // A failed measurement must not raise a load failure — kea-loaders would toast it on a page
        // the user came to for something else.
        await expectLogic(logic).toDispatchActions(['loadAdBlockedCaptureStatsSuccess'])
        await expectLogic(logic).toNotHaveDispatchedActions(['loadAdBlockedCaptureStatsFailure'])
        expect(logic.values.adBlockedCaptureStats).toBeNull()
        expect(logic.values.hasSignificantAdBlockedCapture).toBeNull()
        // A failure reads differently from a measured zero, so the settings row can say so.
        expect(logic.values.adBlockedCaptureFailed).toBe(true)

        await measure([[120, 1000]])

        expect(logic.values.adBlockedCaptureFailed).toBe(false)
    })

    // Each environment has its own loss rate, so a cached measurement must not follow the user
    // into another one.
    it('measures again when the current team changes', async () => {
        await measure([[120, 1000]])
        const appContext = window.POSTHOG_APP_CONTEXT as any
        const originalTeam = appContext.current_team
        appContext.current_team = { ...originalTeam, id: originalTeam.id + 1 }

        try {
            queryResponse = [200, { results: [[10, 1000]] }]
            logic.actions.loadAdBlockedCaptureStats()
            await expectLogic(logic).toDispatchActions(['loadAdBlockedCaptureStatsSuccess'])

            expect(logic.values.adBlockedCaptureShare).toEqual(0.01)
        } finally {
            appContext.current_team = originalTeam
        }
    })
})
