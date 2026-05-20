import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { OrganizationType, UserType } from '~/types'

import { welcomeDialogLogic } from './welcomeDialogLogic'

const INVITED_USER: UserType = {
    ...MOCK_DEFAULT_USER,
    is_organization_first_user: false,
}

const ORG_CREATOR_USER: UserType = {
    ...MOCK_DEFAULT_USER,
    is_organization_first_user: true,
}

const INVITED_USER_NEEDING_2FA: UserType = {
    ...INVITED_USER,
    is_2fa_enabled: false,
    passkeys_enabled_for_2fa: false,
    organization: {
        ...(MOCK_DEFAULT_USER.organization as OrganizationType),
        enforce_2fa: true,
    },
}

const INVITED_USER_WITH_2FA: UserType = {
    ...INVITED_USER_NEEDING_2FA,
    is_2fa_enabled: true,
}

const mockPayload = {
    organization_name: 'Acme Inc',
    inviter: { name: 'Alex', email: 'alex@acme.com' },
    team_members: [{ name: 'Alex', email: 'alex@acme.com', avatar: null, role: 'Owner', last_active: 'today' }],
    recent_activity: [
        {
            type: 'Insight.created',
            actor_name: 'Alex',
            entity_name: 'Signups by day',
            entity_url: '/project/1/insights/abc',
            timestamp: '2026-04-01T12:00:00Z',
        },
    ],
    popular_dashboards: [
        {
            id: 42,
            name: 'Product overview',
            description: 'Signups + revenue',
            team_id: 1,
            url: '/project/1/dashboard/42',
        },
    ],
    products_in_use: ['product_analytics', 'feature_flags'],
    suggested_next_steps: [
        { label: 'See active feature flags', href: '/feature_flags', reason: 'Your team uses Feature flags' },
    ],
    is_organization_first_user: false,
}

describe('welcomeDialogLogic', () => {
    let logic: ReturnType<typeof welcomeDialogLogic.build>

    beforeEach(() => {
        // The dialog persists dismissal in localStorage and "looked around" in sessionStorage —
        // clear both so a prior test doesn't carry over and suppress the dialog.
        window.localStorage.clear()
        window.sessionStorage.clear()
        useMocks({
            get: {
                '/api/organizations/@current/welcome/current/': mockPayload,
            },
        })
        initKeaTests()
        userLogic.mount()
    })

    it('loads welcome data for invitees who have not dismissed', async () => {
        userLogic.actions.loadUserSuccess(INVITED_USER)
        logic = welcomeDialogLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWelcomeData', 'loadWelcomeDataSuccess'])
        expect(logic.values.welcomeData.organization_name).toBe('Acme Inc')
        expect(logic.values.shouldShowDialog).toBe(true)
    })

    it('does not open for the org creator', async () => {
        userLogic.actions.loadUserSuccess(ORG_CREATOR_USER)
        logic = welcomeDialogLogic()
        logic.mount()

        expect(logic.values.shouldShowDialog).toBe(false)
        await expectLogic(logic).toNotHaveDispatchedActions(['loadWelcomeData'])
    })

    it('does not reopen for a user who has already dismissed', async () => {
        window.localStorage.setItem(
            `posthog_welcome_dismissed:${INVITED_USER.uuid}:${INVITED_USER.organization?.id}`,
            '1'
        )
        userLogic.actions.loadUserSuccess(INVITED_USER)
        logic = welcomeDialogLogic()
        logic.mount()

        expect(logic.values.shouldShowDialog).toBe(false)
        await expectLogic(logic).toNotHaveDispatchedActions(['loadWelcomeData'])
    })

    it('persists dismissal to localStorage so the dialog does not reopen', async () => {
        userLogic.actions.loadUserSuccess(INVITED_USER)
        logic = welcomeDialogLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWelcomeDataSuccess'])
        logic.actions.dismissWelcome()
        expect(
            window.localStorage.getItem(
                `posthog_welcome_dismissed:${INVITED_USER.uuid}:${INVITED_USER.organization?.id}`
            )
        ).toBe('1')
        expect(logic.values.shouldShowDialog).toBe(false)
    })

    it('closes locally on closeDialog so it does not flash back', async () => {
        userLogic.actions.loadUserSuccess(INVITED_USER)
        logic = welcomeDialogLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWelcomeDataSuccess'])
        expect(logic.values.shouldShowDialog).toBe(true)
        logic.actions.closeDialog()
        expect(logic.values.shouldShowDialog).toBe(false)
    })

    it('tracks card interactions', async () => {
        userLogic.actions.loadUserSuccess(INVITED_USER)
        logic = welcomeDialogLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWelcomeDataSuccess'])
        logic.actions.trackCardClick('dashboards', '/project/1/dashboard/42')
        expect(logic.values.interactedCards.dashboards).toBe(true)
    })

    it('suppresses the dialog and skips the request when 2FA setup is still pending', async () => {
        userLogic.actions.loadUserSuccess(INVITED_USER_NEEDING_2FA)
        logic = welcomeDialogLogic()
        logic.mount()

        expect(logic.values.isPendingTwoFactorSetup).toBe(true)
        expect(logic.values.shouldShowDialog).toBe(false)
        await expectLogic(logic).toNotHaveDispatchedActions(['loadWelcomeData'])
    })

    it('re-fetches and shows the dialog once 2FA setup completes', async () => {
        userLogic.actions.loadUserSuccess(INVITED_USER_NEEDING_2FA)
        logic = welcomeDialogLogic()
        logic.mount()

        // No fetch while 2FA setup is pending.
        await expectLogic(logic).toNotHaveDispatchedActions(['loadWelcomeData'])
        expect(logic.values.shouldShowDialog).toBe(false)

        // Simulate userLogic refetch after the user completes 2FA setup.
        userLogic.actions.loadUserSuccess(INVITED_USER_WITH_2FA)

        await expectLogic(logic).toDispatchActions(['loadWelcomeData', 'loadWelcomeDataSuccess'])
        expect(logic.values.shouldShowDialog).toBe(true)
        expect(logic.values.welcomeData.organization_name).toBe('Acme Inc')
    })

    it('suppresses the dialog (no error banner) when the API returns 403 two_factor_setup_required', async () => {
        useMocks({
            get: {
                '/api/organizations/@current/welcome/current/': () => [
                    403,
                    { detail: '2FA setup required', code: 'two_factor_setup_required' },
                ],
            },
        })
        // Use a user object where the org's enforce_2fa is null so the pre-emptive selector lets
        // the request through — we want to exercise the response-code fallback path.
        userLogic.actions.loadUserSuccess(INVITED_USER)
        logic = welcomeDialogLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWelcomeData', 'loadWelcomeDataSuccess'])
        expect(logic.values.twoFactorSetupRequired).toBe(true)
        expect(logic.values.welcomeDataError).toBe(false)
        expect(logic.values.shouldShowDialog).toBe(false)
    })
})
