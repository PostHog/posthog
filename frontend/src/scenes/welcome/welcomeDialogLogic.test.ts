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
    welcome_screen_seen_at: null,
}

const ORG_CREATOR_USER: UserType = {
    ...MOCK_DEFAULT_USER,
    is_organization_first_user: true,
    welcome_screen_seen_at: null,
}

const DISMISSED_USER: UserType = {
    ...MOCK_DEFAULT_USER,
    is_organization_first_user: false,
    welcome_screen_seen_at: '2026-04-16T12:00:00Z',
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
        useMocks({
            get: {
                '/api/organizations/@current/welcome/': mockPayload,
            },
            post: {
                '/api/users/@me/welcome_screen/dismiss/': { welcome_screen_seen_at: '2026-04-16T12:00:00Z' },
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
        userLogic.actions.loadUserSuccess(DISMISSED_USER)
        logic = welcomeDialogLogic()
        logic.mount()

        expect(logic.values.shouldShowDialog).toBe(false)
        await expectLogic(logic).toNotHaveDispatchedActions(['loadWelcomeData'])
    })

    it('closes locally on closeDialog so it does not flash back before the refetch', async () => {
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
