import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'lib/posthog-typed'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { dashboardSubscribeNudgeStoreLogic } from 'scenes/dashboard/dashboardSubscribeNudgeStoreLogic'
import { userLogic } from 'scenes/userLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { SubscriptionFreeTierLimit } from '~/queries/schema/schema-general'
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
    MAX_TRACKED_DASHBOARDS,
} from './dashboardSubscribeNudgeStoreLogic'
import { DashboardSubscribeNudgeToast, onDashboardSubscribeNudgeToastCta } from './DashboardSubscribeNudgeToast'

jest.mock('lib/posthog-typed', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))

jest.mock('products/subscriptions/frontend/generated/api', () => ({
    subscriptionsList: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { info: jest.fn(), error: jest.fn(), success: jest.fn(), dismiss: jest.fn() },
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
    let nudgePostCount: number
    let nudgePostResponse: [number, Record<string, unknown>]

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
        ;(lemonToast.info as jest.Mock).mockClear()
        nudgePostCount = 0
        nudgePostResponse = [201, { created: true }]
        now = START_TIME
        dateSpy = jest.spyOn(Date, 'now').mockImplementation(() => now)
        useMocks({
            post: {
                '/api/projects/:team_id/dashboards/:dashboard_id/subscribe_nudge/': () => {
                    nudgePostCount += 1
                    return nudgePostResponse
                },
            },
        })
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

    it('keeps the same viewLog reference on a no-op deduped record', () => {
        // A re-dispatch inside the dedupe window with nothing stale to prune must not mint a new
        // map object, so kea-localstorage skips a redundant full-map persist write.
        logic.actions.recordDashboardView(DASHBOARD_ID)
        const before = dashboardSubscribeNudgeStoreLogic.values.viewLog
        now += 1000
        logic.actions.recordDashboardView(DASHBOARD_ID)
        expect(dashboardSubscribeNudgeStoreLogic.values.viewLog).toBe(before)
    })

    it('prunes stale views across the whole map and drops emptied dashboards', () => {
        recordViews(3)
        recordViews(1, 999) // another dashboard, whose views all go stale

        now += DASHBOARD_VIEW_LOG_WINDOW_MS + 1000
        logic.actions.recordDashboardView(DASHBOARD_ID)

        expect(logic.values.viewCount7d).toBe(1)
        expect(logic.values.isPastViewThreshold).toBe(false)
        // The persisted map is bounded: fully-stale dashboards disappear entirely.
        expect(Object.keys(dashboardSubscribeNudgeStoreLogic.values.viewLog)).toEqual([String(DASHBOARD_ID)])
    })

    describe('free-tier subscription limit', () => {
        beforeEach(() => {
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER) // no available features -> free tier
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DASHBOARD_SUBSCRIBE_NUDGE]: 'test' })
        })

        it.each([
            [0, true],
            [SubscriptionFreeTierLimit.COUNT - 1, true],
            [SubscriptionFreeTierLimit.COUNT, false],
        ])('with %i existing team subscriptions, nudges=%s', async (teamCount, nudges) => {
            mockSubscriptionsList.mockImplementation((_teamId: string, params?: Record<string, unknown>) =>
                Promise.resolve(params?.dashboard ? { count: 0, results: [] } : { count: teamCount, results: [] })
            )

            await expectLogic(logic, () => {
                recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
            }).toFinishAllListeners()

            // On success the flow marks the dashboard notified (isCandidate flips false again),
            // so assert the observable outcomes rather than intermediate selector state.
            expect(logic.values.isWithinSubscriptionLimit).toBe(nudges)
            expect(nudgePostCount).toBe(nudges ? 1 : 0)
            expect(capturesOf('dashboard subscribe nudge shown')).toHaveLength(nudges ? 1 : 0)
        })

        it('fails closed and reports the failure when the count fetch errors', async () => {
            silenceKeaLoadersErrors()
            mockSubscriptionsList.mockImplementation((_teamId: string, params?: Record<string, unknown>) =>
                params?.dashboard
                    ? Promise.resolve({ count: 0, results: [] })
                    : Promise.reject(new Error('network down'))
            )

            await expectLogic(logic, () => {
                recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
            }).toFinishAllListeners()
            resumeKeaLoadersErrors()

            expect(logic.values.isWithinSubscriptionLimit).toBe(false)
            expect(logic.values.showNudge).toBe(false)
            expect(nudgePostCount).toBe(0)
            const failures = capturesOf('dashboard subscribe nudge check failed')
            expect(failures).toHaveLength(1)
            expect(failures[0][1]).toMatchObject({
                dashboard_id: DASHBOARD_ID,
                step: 'limit',
                error_message: 'network down',
            })
        })
    })

    it('never fetches the team-wide count for orgs with the subscriptions feature', async () => {
        await expectLogic(logic, () => {
            recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
        }).toFinishAllListeners()

        const teamWideCalls = mockSubscriptionsList.mock.calls.filter(
            ([, params]: [string, Record<string, unknown> | undefined]) => !params?.dashboard
        )
        expect(teamWideCalls).toHaveLength(0)
    })

    describe('feature flag exposure gating and notification delivery', () => {
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

        it('suppresses the dashboard permanently when it already has a subscription, without reading the flag or notifying', async () => {
            mockSubscriptionsList.mockResolvedValue({ count: 1, results: [{ id: 7 }] })

            await expectLogic(logic, () => {
                recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
            }).toFinishAllListeners()

            expect(logic.values.isSuppressed).toBe(true)
            expect(logic.values.isCandidate).toBe(false)
            expect(logic.values.flagVariant).toBeUndefined()
            expect(mockSubscriptionsList).toHaveBeenCalledTimes(1)
            expect(nudgePostCount).toBe(0)

            // Further views on a suppressed dashboard never re-trigger the check.
            await expectLogic(logic, () => {
                recordViews(1)
            }).toFinishAllListeners()
            expect(mockSubscriptionsList).toHaveBeenCalledTimes(1)
        })

        it('requests the notification once when eligible, reporting shown and toasting on creation', async () => {
            await expectLogic(logic, () => {
                recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
            }).toFinishAllListeners()

            // After a successful delivery the notified marker deliberately ends candidacy,
            // so the observable outcomes are the POST, the marker, the event, and the toast.
            expect(nudgePostCount).toBe(1)
            expect(logic.values.isNotified).toBe(true)
            expect(capturesOf('dashboard subscribe nudge shown')).toEqual([
                [
                    'dashboard subscribe nudge shown',
                    { dashboard_id: DASHBOARD_ID, view_count_7d: DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD },
                ],
            ])
            expect(lemonToast.info).toHaveBeenCalledTimes(1)

            // A further view neither refetches, re-posts, nor re-reports.
            await expectLogic(logic, () => {
                recordViews(1)
            }).toFinishAllListeners()
            expect(mockSubscriptionsList).toHaveBeenCalledTimes(1)
            expect(nudgePostCount).toBe(1)
            expect(capturesOf('dashboard subscribe nudge shown')).toHaveLength(1)
        })

        it('shows a sticky stacked toast carrying the send-time view count', async () => {
            await expectLogic(logic, () => {
                recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
            }).toFinishAllListeners()

            const [body, options] = (lemonToast.info as jest.Mock).mock.calls[0]
            // Sticky: persists until the CTA (which dismisses via the toastId) or the X.
            expect(options).toMatchObject({
                autoClose: false,
                toastId: `dashboard-subscribe-nudge-${DASHBOARD_ID}`,
            })
            expect(body.type).toBe(DashboardSubscribeNudgeToast)
            expect(body.props).toEqual({
                dashboardId: DASHBOARD_ID,
                dashboardName: 'Test dashboard',
                viewCount7d: DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD,
            })
        })

        it('the toast CTA dismisses the toast and routes to the prefilled new-subscription form', () => {
            onDashboardSubscribeNudgeToastCta(DASHBOARD_ID)

            expect(lemonToast.dismiss).toHaveBeenCalledWith(`dashboard-subscribe-nudge-${DASHBOARD_ID}`)
            expect(router.values.location.pathname).toMatch(new RegExp(`/dashboard/${DASHBOARD_ID}/subscriptions/new$`))
            expect(router.values.searchParams).toMatchObject({ prefill: 'nudge', via: 'toast' })
        })

        it('does not burn the client marker when the server reports nothing was created', async () => {
            // created:false covers a server dedupe-skip AND a released sentinel (notifications
            // unavailable / opt-out) — the marker must not stick, so the nudge can retry later.
            nudgePostResponse = [200, { created: false }]

            await expectLogic(logic, () => {
                recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
            }).toFinishAllListeners()

            expect(nudgePostCount).toBe(1)
            expect(logic.values.isNotified).toBe(false)
            expect(capturesOf('dashboard subscribe nudge shown')).toHaveLength(0)
            expect(lemonToast.info).not.toHaveBeenCalled()

            // The next qualifying visit (fresh mount) retries; the server sentinel still
            // collapses genuine duplicates.
            logic.unmount()
            logic = dashboardSubscribeNudgeLogic({ dashboardId: DASHBOARD_ID })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(nudgePostCount).toBe(2)
        })

        it('reports the notify failure and does not mark notified when the delivery request errors', async () => {
            silenceKeaLoadersErrors()
            nudgePostResponse = [500, {}]

            await expectLogic(logic, () => {
                recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
            }).toFinishAllListeners()
            resumeKeaLoadersErrors()

            expect(logic.values.isNotified).toBe(false)
            expect(capturesOf('dashboard subscribe nudge shown')).toHaveLength(0)
            const failures = capturesOf('dashboard subscribe nudge check failed')
            expect(failures).toHaveLength(1)
            expect(failures[0][1]).toMatchObject({ dashboard_id: DASHBOARD_ID, step: 'notify' })
        })

        it('reports the check failure and stays hidden when the eligibility check errors', async () => {
            silenceKeaLoadersErrors()
            mockSubscriptionsList.mockRejectedValue(new Error('network down'))

            await expectLogic(logic, () => {
                recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
            }).toFinishAllListeners()
            resumeKeaLoadersErrors()

            expect(logic.values.showNudge).toBe(false)
            expect(nudgePostCount).toBe(0)
            const failures = capturesOf('dashboard subscribe nudge check failed')
            expect(failures).toHaveLength(1)
            expect(failures[0][1]).toMatchObject({
                dashboard_id: DASHBOARD_ID,
                step: 'check',
                error_message: 'network down',
            })
        })

        it('does not notify already-notified dashboards, and skips their eligibility fetch entirely', async () => {
            dashboardSubscribeNudgeStoreLogic.actions.markDashboardNotified(DASHBOARD_ID)

            await expectLogic(logic, () => {
                recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
            }).toFinishAllListeners()

            expect(logic.values.isCandidate).toBe(false)
            expect(mockSubscriptionsList).not.toHaveBeenCalled()
            expect(nudgePostCount).toBe(0)
        })
    })

    it('does not notify for the control variant', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DASHBOARD_SUBSCRIBE_NUDGE]: 'control' })

        await expectLogic(logic, () => {
            recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
        }).toFinishAllListeners()

        expect(logic.values.isEligible).toBe(true)
        expect(logic.values.showNudge).toBe(false)
        expect(nudgePostCount).toBe(0)
    })

    it('requests the notification when feature flags resolve only after the check completed', async () => {
        // No flag variant yet: the check resolves eligible but the nudge can't fire.
        await expectLogic(logic, () => {
            recordViews(DASHBOARD_SUBSCRIBE_NUDGE_VIEW_THRESHOLD)
        }).toFinishAllListeners()
        expect(nudgePostCount).toBe(0)

        // Flags arrive late — the nudge must still be delivered.
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DASHBOARD_SUBSCRIBE_NUDGE]: 'test' })
        await expectLogic(logic).toFinishAllListeners()

        expect(nudgePostCount).toBe(1)
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
            expect(nudgePostCount).toBe(hasSubscription ? 0 : 1)

            subsLogic.unmount()
        }
    )

    it('caps the suppression list at the most recent entries', () => {
        for (let i = 1; i <= MAX_TRACKED_DASHBOARDS + 1; i++) {
            logic.actions.suppressDashboardNudge(i)
        }
        const suppressed = dashboardSubscribeNudgeStoreLogic.values.suppressedDashboardIds
        expect(suppressed).toHaveLength(MAX_TRACKED_DASHBOARDS)
        expect(suppressed).not.toContain(1) // oldest evicted
        expect(suppressed).toContain(MAX_TRACKED_DASHBOARDS + 1) // newest kept
    })

    it('caps the view log at the most recently viewed dashboards', () => {
        for (let i = 1; i <= MAX_TRACKED_DASHBOARDS + 1; i++) {
            now += 1000
            logic.actions.recordDashboardView(i)
        }
        const trackedIds = Object.keys(dashboardSubscribeNudgeStoreLogic.values.viewLog)
        expect(trackedIds).toHaveLength(MAX_TRACKED_DASHBOARDS)
        expect(trackedIds).not.toContain('1') // least recently viewed evicted
        expect(trackedIds).toContain(String(MAX_TRACKED_DASHBOARDS + 1)) // newest kept
    })
})
