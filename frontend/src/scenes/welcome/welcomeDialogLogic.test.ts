import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { welcomeDialogLogic } from './welcomeDialogLogic'

jest.mock('posthog-js')

const DAY_MS = 24 * 60 * 60 * 1000

const RECENTLY_JOINED_ORGANIZATION = {
    ...MOCK_DEFAULT_USER.organization!,
    membership_joined_at: new Date().toISOString(),
}

const INVITED_USER: UserType = {
    ...MOCK_DEFAULT_USER,
    organization: RECENTLY_JOINED_ORGANIZATION,
    is_organization_first_user: false,
}

const ORG_CREATOR_USER: UserType = {
    ...MOCK_DEFAULT_USER,
    organization: RECENTLY_JOINED_ORGANIZATION,
    is_organization_first_user: true,
}

// A partner-provisioned account: no inviter (so first org user), but onboarding was skipped as
// 'provisioned'. Should still get the welcome dialog even though it isn't an invitee.
const PROVISIONED_USER: UserType = {
    ...MOCK_DEFAULT_USER,
    organization: RECENTLY_JOINED_ORGANIZATION,
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
        // The dialog persists dismissals and closes in localStorage, so clear it to stop a prior
        // test from suppressing the dialog.
        window.localStorage.clear()
        ;(posthog.capture as jest.Mock).mockClear()
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

    it('does not reopen in a new tab after "Don\'t show again"', async () => {
        userLogic.actions.loadUserSuccess(INVITED_USER)
        logic = welcomeDialogLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWelcomeDataSuccess'])
        logic.actions.dismissWelcome()
        expect(logic.values.shouldShowDialog).toBe(false)

        logic.unmount()
        logic = welcomeDialogLogic()
        logic.mount()
        expect(logic.values.shouldShowDialog).toBe(false)
        await expectLogic(logic).toNotHaveDispatchedActions(['loadWelcomeData'])
    })

    it.each(['start_exploring', 'modal_close', 'ask_max_card'] as const)(
        'closes locally on closeDialog from %s and reports which control was used',
        async (source) => {
            userLogic.actions.loadUserSuccess(INVITED_USER)
            logic = welcomeDialogLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadWelcomeDataSuccess'])
            expect(logic.values.shouldShowDialog).toBe(true)
            logic.actions.closeDialog(source)
            expect(logic.values.shouldShowDialog).toBe(false)
            expect(
                (posthog.capture as jest.Mock).mock.calls.filter(([name]) => name === 'welcome_screen_closed')
            ).toEqual([['welcome_screen_closed', expect.objectContaining({ source })]])
        }
    )

    it.each([
        { control: 'closeDialog', close: (): void => logic.actions.closeDialog('start_exploring') },
        { control: 'trackCardClick', close: (): void => logic.actions.trackCardClick('dashboards', '/dashboard/42') },
    ])('stays closed in a new tab after $control', async ({ close }) => {
        userLogic.actions.loadUserSuccess(INVITED_USER)
        logic = welcomeDialogLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWelcomeDataSuccess'])
        close()

        logic.unmount()
        logic = welcomeDialogLogic()
        logic.mount()
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

    it('refetches and shows the new org name after an org switch', async () => {
        // Both orgs keep the dialog eligible, so `shouldShowDialog` never flips and the automatic
        // refetch does not fire — the org-change refetch has to carry it, otherwise the previous
        // org name stays on screen.
        const orgA = { ...INVITED_USER.organization!, id: 'org-a-id', name: 'Acme Inc' }
        const orgB = { ...INVITED_USER.organization!, id: 'org-b-id', name: 'Beta Corp' }
        userLogic.actions.loadUserSuccess({ ...INVITED_USER, organization: orgA })
        logic = welcomeDialogLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWelcomeDataSuccess'])
        expect(logic.values.organizationName).toBe('Acme Inc')

        userLogic.actions.loadUserSuccess({ ...INVITED_USER, organization: orgB })
        // Title must follow the user's current org even before the refetch lands.
        expect(logic.values.organizationName).toBe('Beta Corp')
        await expectLogic(logic).toDispatchActions(['resetForOrgChange', 'loadWelcomeData'])
    })

    it.each([
        { case: 'in the first week', joinedDaysAgo: 1, closedOnDay: null, expected: true },
        { case: 'on the last day of the window', joinedDaysAgo: 13, closedOnDay: null, expected: true },
        { case: 'once two weeks have passed', joinedDaysAgo: 14, closedOnDay: null, expected: false },
        { case: 'long after joining', joinedDaysAgo: 30, closedOnDay: null, expected: false },
        { case: 'after a close in the same week', joinedDaysAgo: 6, closedOnDay: 1, expected: false },
        { case: 'in the week after a close', joinedDaysAgo: 7, closedOnDay: 1, expected: true },
        { case: 'after a close in the second week', joinedDaysAgo: 13, closedOnDay: 8, expected: false },
    ])('shouldShowDialog is $expected $case', ({ joinedDaysAgo, closedOnDay, expected }) => {
        const joinedAt = Date.now() - joinedDaysAgo * DAY_MS
        const user: UserType = {
            ...INVITED_USER,
            organization: { ...RECENTLY_JOINED_ORGANIZATION, membership_joined_at: new Date(joinedAt).toISOString() },
        }
        userLogic.actions.loadUserSuccess(user)
        logic = welcomeDialogLogic()
        logic.mount()
        if (closedOnDay !== null) {
            logic.actions.markClosed(logic.values.membershipKey!, joinedAt + closedOnDay * DAY_MS)
        }

        expect(logic.values.shouldShowDialog).toBe(expected)
    })
})
