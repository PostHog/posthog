import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

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

import { claimExportNudge, dashboardExportNudgeLogic, resolveExportNudgeEligibility } from './dashboardExportNudgeLogic'
import { claimExportNudgeMessage } from './DashboardExportNudgeToast'

jest.mock('lib/posthog-typed', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))

jest.mock('products/subscriptions/frontend/generated/api', () => ({
    subscriptionsList: jest.fn(),
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

    async function considerNudge(dashboardId: number = DASHBOARD_ID): Promise<boolean> {
        const candidate = await resolveExportNudgeEligibility(dashboardId)
        return !!candidate && claimExportNudge(candidate.dashboardId)
    }

    it('nudges an eligible exporter in the test variant', async () => {
        expect(await considerNudge()).toBe(true)

        expect(capturesOf('dashboard export nudge shown')).toEqual([
            ['dashboard export nudge shown', { dashboard_id: DASHBOARD_ID }],
        ])
        expect(storeLogic.values.exportNudgedDashboardIds).toEqual([DASHBOARD_ID])
    })

    it('does not nudge in the control variant', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DASHBOARD_EXPORT_NUDGE]: 'control' })

        // The variant is read only by the second half, so a control exporter still resolves as a
        // candidate. Every other check has to run before the flag read reports exposure.
        expect(await resolveExportNudgeEligibility(DASHBOARD_ID)).toMatchObject({ dashboardId: DASHBOARD_ID })
        expect(claimExportNudge(DASHBOARD_ID)).toBe(false)
        // Not marked either, so a later rollout to this user isn't already burnt.
        expect(storeLogic.values.exportNudgedDashboardIds).toEqual([])
    })

    it('nudges a dashboard only once, even across repeated exports', async () => {
        expect(await considerNudge()).toBe(true)
        expect(await considerNudge()).toBe(false)
    })

    it('nudges a dashboard only once when two of its exports run concurrently', async () => {
        // Exporting the same dashboard as PNG and CSV back to back runs both eligibility checks
        // before either export claims, so the claim itself has to be what excludes the second.
        expect(await Promise.all([considerNudge(), considerNudge()])).toEqual([true, false])

        expect(capturesOf('dashboard export nudge shown')).toHaveLength(1)
    })

    it('suppresses the dashboard when it already has a subscription', async () => {
        mockSubscriptionCounts({ dashboardCount: 1 })

        expect(await considerNudge()).toBe(false)
        // Shared with the repeat-view nudge: someone who already subscribed is done being asked.
        expect(storeLogic.values.suppressedDashboardIds).toEqual([DASHBOARD_ID])
    })

    it('does not nudge a dashboard the repeat-view nudge already suppressed', async () => {
        storeLogic.actions.suppressDashboardNudge(DASHBOARD_ID)

        expect(await considerNudge()).toBe(false)
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

            expect(await considerNudge()).toBe(nudges)
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

            expect(await considerNudge()).toBe(false)
            expect(capturesOf('dashboard export nudge check failed')).toHaveLength(1)
            expect(capturesOf('dashboard export nudge check failed')[0][1]).toMatchObject({
                dashboard_id: DASHBOARD_ID,
                step: 'check',
            })
        })

        it('fails closed and reports when the free-tier count breaks', async () => {
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
            mockSubscriptionsList.mockRejectedValue({ name: 'ApiError', status: 500, message: 'boom' })

            expect(await considerNudge()).toBe(false)
            expect(capturesOf('dashboard export nudge check failed')[0][1]).toMatchObject({ step: 'limit' })
        })
    })

    describe('nudge toast message', () => {
        const TOAST_ID = 'export-toast'
        const CANDIDATE = { dashboardId: DASHBOARD_ID, dashboardName: 'Weekly numbers' }
        let dismiss: jest.SpyInstance

        beforeEach(() => {
            dismiss = jest.spyOn(lemonToast, 'dismiss').mockImplementation(() => {})
        })

        afterEach(() => {
            cleanup()
            dismiss.mockRestore()
        })

        it('renders nothing without a candidate', () => {
            expect(claimExportNudgeMessage(null, TOAST_ID)).toBeNull()
        })

        it('renders nothing for an exporter outside the test variant', () => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DASHBOARD_EXPORT_NUDGE]: 'control' })

            expect(claimExportNudgeMessage(CANDIDATE, TOAST_ID)).toBeNull()
        })

        it('the CTA dismisses the toast and routes to the prefilled new-subscription form', () => {
            const renderer = claimExportNudgeMessage(CANDIDATE, TOAST_ID)
            render(renderer!('Export complete!'))

            fireEvent.click(screen.getByText('Set up recurring updates'))

            expect(dismiss).toHaveBeenCalledWith(TOAST_ID)
            expect(router.values.location.pathname).toMatch(new RegExp(`/dashboard/${DASHBOARD_ID}/subscriptions/new$`))
            expect(router.values.searchParams).toMatchObject({ prefill: 'nudge', via: 'export' })
        })

        it('keeps the toast up when the secondary action fires', () => {
            const action = jest.fn()
            const renderer = claimExportNudgeMessage(CANDIDATE, TOAST_ID)
            render(renderer!('Preparing export…', { label: 'View exports', action }))

            fireEvent.click(screen.getByText('View exports'))

            expect(action).toHaveBeenCalled()
            // A side trip to the exports panel must not silently take the nudge with it.
            expect(dismiss).not.toHaveBeenCalled()
        })
    })
})
