import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'lib/posthog-typed'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { dashboardViewLogLogic } from 'scenes/dashboard/dashboardViewLogLogic'
import { userLogic } from 'scenes/userLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    AccessControlLevel,
    AvailableFeature,
    DashboardPlacement,
    DashboardType,
    QueryBasedInsightModel,
    UserType,
} from '~/types'

import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'
import { subscriptionsList } from 'products/subscriptions/frontend/generated/api'

import { DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD, dashboardSubscribeNudgeLogic } from './dashboardSubscribeNudgeLogic'
import {
    DASHBOARD_VIEW_DEDUPE_WINDOW_MS,
    DASHBOARD_VIEW_LOG_WINDOW_MS,
    MAX_SUPPRESSED_DASHBOARDS,
    MAX_TRACKED_DASHBOARDS,
} from './dashboardViewLogLogic'

jest.mock('lib/posthog-typed', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))

jest.mock('products/subscriptions/frontend/generated/api', () => ({
    subscriptionsList: jest.fn(),
}))

const mockSubscriptionsList = subscriptionsList as jest.Mock

const DASHBOARD_ID = 1
const START_TIME = 1_700_000_000_000

const USER_WITH_SUBSCRIPTIONS_FEATURE: UserType = {
    ...MOCK_DEFAULT_USER,
    organization: {
        ...MOCK_DEFAULT_ORGANIZATION,
        available_product_features: [{ key: AvailableFeature.SUBSCRIPTIONS, name: 'Subscriptions' }],
    },
}

function mockDashboard(): DashboardType<QueryBasedInsightModel> {
    return {
        id: DASHBOARD_ID,
        name: 'Test dashboard',
        user_access_level: AccessControlLevel.Editor,
        tiles: [],
    } as unknown as DashboardType<QueryBasedInsightModel>
}

function capturesOf(event: string): any[][] {
    return (posthog.capture as jest.Mock).mock.calls.filter(([name]) => name === event)
}

describe('dashboardSubscribeNudgeLogic', () => {
    let logic: ReturnType<typeof dashboardSubscribeNudgeLogic.build>
    let now: number
    let dateSpy: jest.SpyInstance

    /** Records views spaced beyond the dedupe window, so each counts as a distinct visit. */
    function recordViews(count: number, dashboardId: number = DASHBOARD_ID): void {
        for (let i = 0; i < count; i++) {
            now += DASHBOARD_VIEW_DEDUPE_WINDOW_MS + 1000
            logic.actions.recordDashboardView(dashboardId)
        }
    }

    beforeEach(() => {
        window.localStorage.clear()
        mockSubscriptionsList.mockReset()
        mockSubscriptionsList.mockResolvedValue({ count: 0, results: [] })
        now = START_TIME
        dateSpy = jest.spyOn(Date, 'now').mockImplementation(() => now)
        initKeaTests()
        userLogic.mount()
        userLogic.actions.loadUserSuccess(USER_WITH_SUBSCRIPTIONS_FEATURE)
        featureFlagLogic.mount()
        dashboardLogic({
            id: DASHBOARD_ID,
            dashboard: mockDashboard(),
            placement: DashboardPlacement.Dashboard,
        }).mount()
        logic = dashboardSubscribeNudgeLogic({ dashboardId: DASHBOARD_ID })
        logic.mount()
        ;(posthog.capture as jest.Mock).mockClear()
    })

    afterEach(() => {
        logic.unmount()
        dateSpy.mockRestore()
        window.localStorage.clear()
    })

    it.each([
        [1, false],
        [2, false],
        [DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD, true],
        [DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD + 1, true],
    ])('treats %i view(s) in the last 7 days as past-threshold=%s', (viewCount, expected) => {
        recordViews(viewCount)
        expect(logic.values.viewCount7d).toBe(viewCount)
        expect(logic.values.isPastViewThreshold).toBe(expected)
    })

    it('counts re-dispatches within the dedupe window as a single visit', () => {
        // dashboardLogic can dispatch reportDashboardViewed twice per real page view
        // (mount + after-API-load), so back-to-back records must count once.
        logic.actions.recordDashboardView(DASHBOARD_ID)
        now += 1000
        logic.actions.recordDashboardView(DASHBOARD_ID)
        expect(logic.values.viewCount7d).toBe(1)

        // A genuinely separate visit (past the window) counts again.
        now += DASHBOARD_VIEW_DEDUPE_WINDOW_MS + 1000
        logic.actions.recordDashboardView(DASHBOARD_ID)
        expect(logic.values.viewCount7d).toBe(2)
    })

    it('prunes stale views across the whole map and drops emptied dashboards', () => {
        recordViews(3)
        recordViews(1, 999) // another dashboard, whose views all go stale

        now += DASHBOARD_VIEW_LOG_WINDOW_MS + 1000
        logic.actions.recordDashboardView(DASHBOARD_ID)

        expect(logic.values.viewCount7d).toBe(1)
        expect(logic.values.isPastViewThreshold).toBe(false)
        // The persisted map is bounded: fully-stale dashboards disappear entirely.
        expect(Object.keys(dashboardViewLogLogic.values.viewLog)).toEqual([String(DASHBOARD_ID)])
    })

    it('drops out of candidacy once dismissed and reports the dismissal', async () => {
        recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
        expect(logic.values.isCandidate).toBe(true)

        await expectLogic(logic, () => {
            logic.actions.dismiss()
        }).toFinishAllListeners()

        expect(logic.values.isCandidate).toBe(false)
        expect(capturesOf('dashboard subscribe nudge dismissed')).toEqual([
            [
                'dashboard subscribe nudge dismissed',
                { dashboard_id: DASHBOARD_ID, view_count_7d: DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD },
            ],
        ])
    })

    it('is not a candidate and fetches nothing when the org lacks the subscriptions feature', async () => {
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER) // no available features

        await expectLogic(logic, () => {
            recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
        }).toFinishAllListeners()

        expect(logic.values.isCandidate).toBe(false)
        expect(logic.values.showNudge).toBe(false)
        expect(mockSubscriptionsList).not.toHaveBeenCalled()
    })

    describe('feature flag exposure gating', () => {
        beforeEach(() => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DASHBOARD_SUBSCRIBE_NUDGE]: 'test' })
        })

        it('does not read the flag while the existing-subscription check is in flight', () => {
            recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)

            // Synchronously after the threshold view: the check hasn't resolved yet.
            expect(logic.values.hasExistingSubscription).toBeNull()
            expect(logic.values.isEligible).toBe(false)
            expect(logic.values.flagVariant).toBeUndefined()
        })

        it('suppresses the dashboard permanently when it already has a subscription, without reading the flag', async () => {
            mockSubscriptionsList.mockResolvedValue({ count: 1, results: [{ id: 7 }] })

            await expectLogic(logic, () => {
                recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
            }).toFinishAllListeners()

            expect(logic.values.isSuppressed).toBe(true)
            expect(logic.values.isCandidate).toBe(false)
            expect(logic.values.flagVariant).toBeUndefined()
            expect(mockSubscriptionsList).toHaveBeenCalledTimes(1)

            // Further views on a suppressed dashboard never re-trigger the check.
            await expectLogic(logic, () => {
                recordViews(1)
            }).toFinishAllListeners()
            expect(mockSubscriptionsList).toHaveBeenCalledTimes(1)
        })

        it('reads the flag and shows the banner once eligible, reporting a single shown event', async () => {
            await expectLogic(logic, () => {
                recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
            }).toFinishAllListeners()

            expect(logic.values.isEligible).toBe(true)
            expect(logic.values.flagVariant).toBe('test')
            expect(logic.values.showNudge).toBe(true)
            expect(mockSubscriptionsList).toHaveBeenCalledTimes(1)

            // A further view neither refetches nor re-reports the shown event.
            await expectLogic(logic, () => {
                recordViews(1)
            }).toFinishAllListeners()

            expect(mockSubscriptionsList).toHaveBeenCalledTimes(1)
            expect(capturesOf('dashboard subscribe nudge shown')).toEqual([
                [
                    'dashboard subscribe nudge shown',
                    { dashboard_id: DASHBOARD_ID, view_count_7d: DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD },
                ],
            ])
        })

        it('re-checks when the subscriptions modal closes and hides the banner if a subscription was created', async () => {
            await expectLogic(logic, () => {
                recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
            }).toFinishAllListeners()
            expect(logic.values.showNudge).toBe(true)

            // The user opens the modal, creates a subscription, then closes it.
            logic.actions.setSubscriptionMode(true, 'new')
            mockSubscriptionsList.mockResolvedValue({ count: 1, results: [{ id: 7 }] })
            await expectLogic(logic, () => {
                logic.actions.setSubscriptionMode(false, undefined)
            }).toFinishAllListeners()

            expect(logic.values.hasExistingSubscription).toBe(true)
            expect(logic.values.isSuppressed).toBe(true)
            expect(logic.values.showNudge).toBe(false)
        })

        it('does not re-fetch on a plain navigation-driven modal-close dispatch', async () => {
            await expectLogic(logic, () => {
                recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
            }).toFinishAllListeners()
            expect(mockSubscriptionsList).toHaveBeenCalledTimes(1)

            // Every /dashboard/:id navigation dispatches setSubscriptionMode(false) without the
            // modal ever having been open — that must not re-trigger the check.
            await expectLogic(logic, () => {
                logic.actions.setSubscriptionMode(false, undefined)
            }).toFinishAllListeners()
            expect(mockSubscriptionsList).toHaveBeenCalledTimes(1)
        })

        it('reports the check failure and stays hidden when the eligibility check errors', async () => {
            silenceKeaLoadersErrors()
            mockSubscriptionsList.mockRejectedValue(new Error('network down'))

            await expectLogic(logic, () => {
                recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
            }).toFinishAllListeners()
            resumeKeaLoadersErrors()

            expect(logic.values.showNudge).toBe(false)
            expect(capturesOf('dashboard subscribe nudge check failed')).toEqual([
                [
                    'dashboard subscribe nudge check failed',
                    {
                        dashboard_id: DASHBOARD_ID,
                        error_name: 'Error',
                        error_status: undefined,
                        error_message: 'network down',
                    },
                ],
            ])
        })
    })

    it('captures the shown event when feature flags resolve only after the check completed', async () => {
        // No flag variant yet: the check resolves eligible but the banner can't render.
        await expectLogic(logic, () => {
            recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
        }).toFinishAllListeners()
        expect(logic.values.showNudge).toBe(false)
        expect(capturesOf('dashboard subscribe nudge shown')).toHaveLength(0)

        // Flags arrive late — the banner now renders, and the impression must still be captured.
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DASHBOARD_SUBSCRIBE_NUDGE]: 'test' })

        expect(logic.values.showNudge).toBe(true)
        expect(capturesOf('dashboard subscribe nudge shown')).toHaveLength(1)
    })

    it.each([
        [true, 1],
        [false, 0],
    ])(
        'reuses an already-mounted subscriptionsLogic without calling the API (has subscription: %s)',
        async (hasSubscription, expectedCount) => {
            useMocks({
                get: {
                    '/api/environments/:team_id/subscriptions': {
                        count: expectedCount,
                        results: hasSubscription ? [{ id: 7 }] : [],
                    },
                },
            })
            const subsLogic = subscriptionsLogic({ dashboardId: DASHBOARD_ID })
            subsLogic.mount()
            await expectLogic(subsLogic).toFinishAllListeners()

            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DASHBOARD_SUBSCRIBE_NUDGE]: 'test' })
            await expectLogic(logic, () => {
                recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
            }).toFinishAllListeners()

            expect(mockSubscriptionsList).not.toHaveBeenCalled()
            expect(logic.values.hasExistingSubscription).toBe(hasSubscription)
            expect(logic.values.showNudge).toBe(!hasSubscription)

            subsLogic.unmount()
        }
    )

    it('subscribeClicked sets the prefill, reports the click, and routes to the new-subscription modal', async () => {
        recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)

        await expectLogic(logic, () => {
            logic.actions.subscribeClicked()
        }).toFinishAllListeners()

        expect(logic.values.subscriptionPrefill).toEqual({
            title: 'Test dashboard weekly digest',
            target_value: MOCK_DEFAULT_USER.email,
        })
        expect(capturesOf('dashboard subscribe nudge clicked')).toEqual([
            [
                'dashboard subscribe nudge clicked',
                {
                    dashboard_id: DASHBOARD_ID,
                    view_count_7d: DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD,
                    prefilled: true,
                },
            ],
        ])
        expect(router.values.location.pathname).toMatch(new RegExp(`/dashboard/${DASHBOARD_ID}/subscriptions/new$`))
    })

    it.each([
        ['modal close', false, undefined, true],
        ['cancel back to the subscriptions list', true, undefined, true],
        ['staying on the new form', true, 'new' as const, false],
    ])('prefill lifecycle on %s', (_label, enabled, id, expectCleared) => {
        logic.actions.setSubscriptionPrefill({ title: 'Nudge title' })

        logic.actions.setSubscriptionMode(enabled, id)

        // A stale prefill must not leak into a later, unrelated "+ New subscription" open.
        expect(logic.values.subscriptionPrefill).toEqual(expectCleared ? null : { title: 'Nudge title' })
    })

    it('caps the suppression list at the most recent entries', () => {
        for (let i = 1; i <= MAX_SUPPRESSED_DASHBOARDS + 1; i++) {
            logic.actions.suppressDashboardNudge(i)
        }
        const suppressed = dashboardViewLogLogic.values.suppressedDashboardIds
        expect(suppressed).toHaveLength(MAX_SUPPRESSED_DASHBOARDS)
        expect(suppressed).not.toContain(1) // oldest evicted
        expect(suppressed).toContain(MAX_SUPPRESSED_DASHBOARDS + 1) // newest kept
    })

    it('caps the view log at the most recently viewed dashboards', () => {
        for (let i = 1; i <= MAX_TRACKED_DASHBOARDS + 1; i++) {
            now += 1000
            logic.actions.recordDashboardView(i)
        }
        const trackedIds = Object.keys(dashboardViewLogLogic.values.viewLog)
        expect(trackedIds).toHaveLength(MAX_TRACKED_DASHBOARDS)
        expect(trackedIds).not.toContain('1') // least recently viewed evicted
        expect(trackedIds).toContain(String(MAX_TRACKED_DASHBOARDS + 1)) // newest kept
    })
})
