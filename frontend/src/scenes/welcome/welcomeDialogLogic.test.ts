import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { welcomeDialogLogic } from './welcomeDialogLogic'

const INVITED_USER: UserType = {
    ...MOCK_DEFAULT_USER,
    is_organization_first_user: false,
}

const ORG_CREATOR_USER: UserType = {
    ...MOCK_DEFAULT_USER,
    is_organization_first_user: true,
}

// A partner-provisioned account: no inviter (so first org user), but onboarding was skipped as
// 'provisioned'. Should still get the welcome dialog even though it isn't an invitee.
const PROVISIONED_USER: UserType = {
    ...MOCK_DEFAULT_USER,
    is_organization_first_user: true,
    onboarding_skipped_reason: 'provisioned',
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
        // The dialog persists its "dismissed" and "seen" suppression markers in localStorage —
        // clear it so a prior test doesn't carry over and suppress the dialog.
        window.localStorage.clear()
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

    it('opens for a partner-provisioned user even though they are the first org user', async () => {
        userLogic.actions.loadUserSuccess(PROVISIONED_USER)
        logic = welcomeDialogLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWelcomeData', 'loadWelcomeDataSuccess'])
        expect(logic.values.shouldShowDialog).toBe(true)
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

    it('does not reopen after being shown once, even across a remount', async () => {
        userLogic.actions.loadUserSuccess(INVITED_USER)
        logic = welcomeDialogLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWelcomeDataSuccess'])
        expect(logic.values.shouldShowDialog).toBe(true)
        logic.unmount()

        // Navigating into a non-home scene unmounts the logic; returning remounts it fresh. The
        // durable "seen" marker must keep it from re-opening and re-fetching (which re-fires
        // welcome_screen_shown) — the bug this guards against.
        const remounted = welcomeDialogLogic()
        remounted.mount()
        expect(remounted.values.shouldShowDialog).toBe(false)
        await expectLogic(remounted).toNotHaveDispatchedActions(['loadWelcomeData'])
        remounted.unmount()
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
})
