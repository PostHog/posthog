import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'lib/posthog-typed'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardPlacement, DashboardType, QueryBasedInsightModel } from '~/types'

import {
    DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD,
    DASHBOARD_SUBSCRIBE_NUDGE_WINDOW_MS,
    dashboardSubscribeNudgeLogic,
} from './dashboardSubscribeNudgeLogic'

jest.mock('lib/posthog-typed', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))

const DASHBOARD_ID = 1

function mockDashboard(
    overrides: Partial<DashboardType<QueryBasedInsightModel>> = {}
): DashboardType<QueryBasedInsightModel> {
    return {
        id: DASHBOARD_ID,
        name: 'Test dashboard',
        user_access_level: AccessControlLevel.Editor,
        tiles: [],
        ...overrides,
    } as DashboardType<QueryBasedInsightModel>
}

describe('dashboardSubscribeNudgeLogic', () => {
    let logic: ReturnType<typeof dashboardSubscribeNudgeLogic.build>

    beforeEach(() => {
        window.localStorage.clear()
        initKeaTests()
        featureFlagLogic.mount()
        const dashLogic = dashboardLogic({
            id: DASHBOARD_ID,
            dashboard: mockDashboard(),
            placement: DashboardPlacement.Dashboard,
        })
        dashLogic.mount()
        logic = dashboardSubscribeNudgeLogic({ dashboardId: DASHBOARD_ID })
        logic.mount()
        ;(posthog.capture as jest.Mock).mockClear()
    })

    afterEach(() => {
        logic.unmount()
        window.localStorage.clear()
    })

    it.each([
        [1, false],
        [2, false],
        [DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD, true],
        [DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD + 1, true],
    ])('treats %i view(s) in the last 7 days as past-threshold=%s', (viewCount, expected) => {
        for (let i = 0; i < viewCount; i++) {
            logic.actions.recordView()
        }
        expect(logic.values.viewCount7d).toBe(viewCount)
        expect(logic.values.isPastViewThreshold).toBe(expected)
    })

    it('prunes views older than 7 days out of the rolling count', () => {
        const dateSpy = jest.spyOn(Date, 'now')
        const oldTime = 1_700_000_000_000
        const freshTime = oldTime + DASHBOARD_SUBSCRIBE_NUDGE_WINDOW_MS + 1000

        dateSpy.mockReturnValue(oldTime)
        logic.actions.recordView()
        logic.actions.recordView()
        logic.actions.recordView()

        dateSpy.mockReturnValue(freshTime)
        logic.actions.recordView()

        expect(logic.values.viewCount7d).toBe(1)
        expect(logic.values.isPastViewThreshold).toBe(false)

        dateSpy.mockRestore()
    })

    it('drops out of candidacy once dismissed, even past the view threshold, and reports the dismissal', () => {
        for (let i = 0; i < DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD; i++) {
            logic.actions.recordView()
        }
        expect(logic.values.isCandidate).toBe(true)

        logic.actions.dismiss()

        expect(logic.values.isCandidate).toBe(false)
        expect(posthog.capture).toHaveBeenCalledWith('dashboard subscribe nudge dismissed', {
            dashboard_id: DASHBOARD_ID,
            view_count_7d: DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD,
        })
    })

    describe('feature flag exposure gating', () => {
        beforeEach(() => {
            for (let i = 0; i < DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD; i++) {
                logic.actions.recordView()
            }
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DASHBOARD_SUBSCRIBE_NUDGE]: 'test' })
        })

        it('does not read the flag while the existing-subscription check is still unresolved', () => {
            expect(logic.values.isEligible).toBe(false)
            expect(logic.values.flagVariant).toBeUndefined()
            expect(logic.values.showNudge).toBe(false)
        })

        it('does not read the flag when the dashboard already has a subscription', () => {
            logic.actions.setHasExistingSubscription(true)

            expect(logic.values.isEligible).toBe(false)
            expect(logic.values.flagVariant).toBeUndefined()
            expect(logic.values.showNudge).toBe(false)
        })

        it('reads the flag and shows the banner once eligible, reporting a single shown event', () => {
            logic.actions.setHasExistingSubscription(false)
            logic.actions.setHasExistingSubscription(false) // re-evaluating must not double-report

            expect(logic.values.isEligible).toBe(true)
            expect(logic.values.flagVariant).toBe('test')
            expect(logic.values.showNudge).toBe(true)

            const shownCalls = (posthog.capture as jest.Mock).mock.calls.filter(
                ([name]) => name === 'dashboard subscribe nudge shown'
            )
            expect(shownCalls).toEqual([
                ['dashboard subscribe nudge shown', { dashboard_id: DASHBOARD_ID, view_count_7d: 3 }],
            ])
        })
    })
})
