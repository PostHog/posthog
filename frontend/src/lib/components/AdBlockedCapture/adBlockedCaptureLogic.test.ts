import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { adBlockedCaptureLogic } from './adBlockedCaptureLogic'

describe('adBlockedCaptureLogic', () => {
    let logic: ReturnType<typeof adBlockedCaptureLogic.build>
    let queryResponse: [number, Record<string, any>]

    beforeEach(() => {
        queryResponse = [200, { results: [] }]
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
    })

    const measure = async (results: any[][]): Promise<void> => {
        queryResponse = [200, { results }]
        logic.actions.loadAdBlockedCaptureStats()
        await expectLogic(logic).toDispatchActions(['loadAdBlockedCaptureStatsSuccess'])
    }

    it('reads the blocked and total session counts from the query', async () => {
        await measure([[120, 1000]])

        expect(logic.values.adBlockedCaptureStats).toEqual({ blockedSessions: 120, totalSessions: 1000 })
        expect(logic.values.adBlockedCaptureShare).toEqual(0.12)
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
        logic.actions.loadAdBlockedCaptureStats()

        // A failed measurement must not raise a load failure — kea-loaders would toast it on a page
        // the user came to for something else.
        await expectLogic(logic).toDispatchActions(['loadAdBlockedCaptureStatsSuccess'])
        await expectLogic(logic).toNotHaveDispatchedActions(['loadAdBlockedCaptureStatsFailure'])
        expect(logic.values.adBlockedCaptureStats).toBeNull()
        expect(logic.values.hasSignificantAdBlockedCapture).toBeNull()
    })
})
