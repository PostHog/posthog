import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'lib/posthog-typed'
import {
    dashboardNudgeScopeKey,
    dashboardSubscribeNudgeStoreLogic,
} from 'scenes/dashboard/dashboardSubscribeNudgeStoreLogic'
import { userLogic } from 'scenes/userLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { SubscriptionFreeTierLimit } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, UserType } from '~/types'

import { subscriptionsList } from 'products/subscriptions/frontend/generated/api'

import { dashboardExportNudgeLogic } from './dashboardExportNudgeLogic'

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

const USER_WITH_SUBSCRIPTIONS_FEATURE: UserType = {
    ...MOCK_DEFAULT_USER,
    organization: {
        ...MOCK_DEFAULT_ORGANIZATION,
        available_product_features: [{ key: AvailableFeature.SUBSCRIPTIONS, name: 'Subscriptions' }],
    },
}

function capturesOf(event: string): any[][] {
    return (posthog.capture as jest.Mock).mock.calls.filter(([name]) => name === event)
}

describe('dashboardExportNudgeLogic', () => {
    let logic: ReturnType<typeof dashboardExportNudgeLogic.build>
    let storeLogic: ReturnType<typeof dashboardSubscribeNudgeStoreLogic.build>

    /** Resolves the dashboard-scoped check and the team-wide free-tier count independently. */
    function mockSubscriptionCounts({
        dashboardCount,
        teamCount = 0,
    }: {
        dashboardCount: number
        teamCount?: number
    }): void {
        mockSubscriptionsList.mockImplementation((_teamId: string, params?: Record<string, unknown>) =>
            Promise.resolve(
                params?.dashboard ? { count: dashboardCount, results: [] } : { count: teamCount, results: [] }
            )
        )
    }

    beforeEach(() => {
        window.localStorage.clear()
        mockSubscriptionsList.mockReset()
        mockSubscriptionCounts({ dashboardCount: 0 })
        ;(lemonToast.info as jest.Mock).mockClear()
        initKeaTests()
        userLogic.mount()
        userLogic.actions.loadUserSuccess(USER_WITH_SUBSCRIPTIONS_FEATURE)
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DASHBOARD_EXPORT_NUDGE]: 'test' })
        logic = dashboardExportNudgeLogic()
        logic.mount()
        storeLogic = dashboardSubscribeNudgeStoreLogic({ scope: dashboardNudgeScopeKey() })
        ;(posthog.capture as jest.Mock).mockClear()
    })

    afterEach(() => {
        logic.unmount()
        window.localStorage.clear()
    })

    async function considerNudge(dashboardId: number = DASHBOARD_ID): Promise<void> {
        await expectLogic(logic, () => {
            logic.actions.considerExportNudge(dashboardId)
        }).toFinishAllListeners()
    }

    it('nudges an eligible exporter in the test variant', async () => {
        await considerNudge()

        expect(lemonToast.info).toHaveBeenCalledTimes(1)
        expect(capturesOf('dashboard export nudge shown')).toEqual([
            ['dashboard export nudge shown', { dashboard_id: DASHBOARD_ID }],
        ])
        expect(storeLogic.values.exportNudgedDashboardIds).toEqual([DASHBOARD_ID])
    })

    it('does not nudge in the control variant', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DASHBOARD_EXPORT_NUDGE]: 'control' })

        await considerNudge()

        expect(lemonToast.info).not.toHaveBeenCalled()
        // Not marked either, so a later rollout to this user isn't already burnt.
        expect(storeLogic.values.exportNudgedDashboardIds).toEqual([])
    })

    it('nudges a dashboard only once, even across repeated exports', async () => {
        await considerNudge()
        await considerNudge()

        expect(lemonToast.info).toHaveBeenCalledTimes(1)
    })

    it('suppresses the dashboard when it already has a subscription', async () => {
        mockSubscriptionCounts({ dashboardCount: 1 })

        await considerNudge()

        expect(lemonToast.info).not.toHaveBeenCalled()
        // Shared with the repeat-view nudge: someone who already subscribed is done being asked.
        expect(storeLogic.values.suppressedDashboardIds).toEqual([DASHBOARD_ID])
    })

    it('does not nudge a dashboard the repeat-view nudge already suppressed', async () => {
        storeLogic.actions.suppressDashboardNudge(DASHBOARD_ID)

        await considerNudge()

        expect(lemonToast.info).not.toHaveBeenCalled()
        expect(mockSubscriptionsList).not.toHaveBeenCalled()
    })

    describe('free-tier subscription limit', () => {
        beforeEach(() => {
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER) // no available features -> free tier
        })

        it.each([
            [0, true],
            [SubscriptionFreeTierLimit.COUNT - 1, true],
            [SubscriptionFreeTierLimit.COUNT, false],
        ])('with %i existing team subscriptions, nudges=%s', async (teamCount, nudges) => {
            mockSubscriptionCounts({ dashboardCount: 0, teamCount })

            await considerNudge()

            expect(lemonToast.info).toHaveBeenCalledTimes(nudges ? 1 : 0)
        })
    })

    describe('failed eligibility checks', () => {
        beforeEach(() => {
            silenceKeaLoadersErrors()
        })

        afterEach(() => {
            resumeKeaLoadersErrors()
        })

        it('fails closed and reports when the dashboard check breaks', async () => {
            mockSubscriptionsList.mockRejectedValue({ name: 'ApiError', status: 500, message: 'boom' })

            await considerNudge()

            expect(lemonToast.info).not.toHaveBeenCalled()
            expect(capturesOf('dashboard export nudge check failed')).toHaveLength(1)
            expect(capturesOf('dashboard export nudge check failed')[0][1]).toMatchObject({
                dashboard_id: DASHBOARD_ID,
                step: 'check',
            })
        })

        it('fails closed and reports when the free-tier count breaks', async () => {
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
            mockSubscriptionsList.mockRejectedValue({ name: 'ApiError', status: 500, message: 'boom' })

            await considerNudge()

            expect(lemonToast.info).not.toHaveBeenCalled()
            expect(capturesOf('dashboard export nudge check failed')[0][1]).toMatchObject({ step: 'limit' })
        })
    })
})
