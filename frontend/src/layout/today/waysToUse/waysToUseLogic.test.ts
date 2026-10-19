import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { twoFactorLogic } from 'scenes/authentication/two-factor-setup/twoFactorLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { IntegrationType, UserType } from '~/types'

import {
    WAYS_TO_USE_SEEN_KEY,
    WaysToUseEligibility,
    shouldOfferWaysToUse,
    teamWorkItems,
    waysToUseSlackState,
    waysToUseSteps,
    waysToUseVariant,
} from './waysToUse'
import { waysToUseLogic } from './waysToUseLogic'

const NOW = Date.parse('2026-10-16T12:00:00Z')
const ORGANIZATION_ID = MOCK_DEFAULT_USER.organization!.id
const SEEN_KEY = `${WAYS_TO_USE_SEEN_KEY}:${ORGANIZATION_ID}`

const user = (overrides: Partial<UserType> = {}, membershipJoinedAt = '2026-10-15T09:00:00Z'): UserType =>
    ({
        ...MOCK_DEFAULT_USER,
        date_joined: '2026-01-01T09:00:00Z',
        organization: { ...MOCK_DEFAULT_USER.organization!, membership_joined_at: membershipJoinedAt },
        has_seen_product_intro_for: {},
        ...overrides,
    }) as UserType

const eligibility = (overrides: Partial<WaysToUseEligibility> = {}): WaysToUseEligibility => ({
    todayRailEnabled: true,
    onHome: true,
    user: user(),
    blocked: false,
    now: NOW,
    ...overrides,
})

describe('waysToUse', () => {
    it('offers the dialog to a new member on Today home, even when the account is older', () => {
        expect(shouldOfferWaysToUse(eligibility())).toBe(true)
    })

    it.each([
        ['the new web is off', { todayRailEnabled: false }],
        ['the user is on another page', { onHome: false }],
        ['the user has not loaded', { user: null }],
        ['a blocking modal is open', { blocked: true }],
        [
            'the user closed it in this organization',
            { user: user({ has_seen_product_intro_for: { [SEEN_KEY]: true } }) },
        ],
        ['the membership is older than two weeks', { user: user({}, '2026-09-30T09:00:00Z') }],
    ])('does not offer the dialog when %s', (_label, overrides) => {
        expect(shouldOfferWaysToUse(eligibility(overrides))).toBe(false)
    })

    it('offers the dialog again in an organization the user just joined', () => {
        const closedElsewhere = user({ has_seen_product_intro_for: { [`${WAYS_TO_USE_SEEN_KEY}:other-org`]: true } })
        expect(shouldOfferWaysToUse(eligibility({ user: closedElsewhere }))).toBe(true)
    })

    it.each([
        ['the organization creator', user({ is_organization_first_user: true }), false, 'creator'],
        ['an invited member', user({ is_organization_first_user: false }), false, 'invitee'],
        ['a provisioned first user', user({ is_organization_first_user: true }), true, 'invitee'],
    ])('shows %s the %s variant', (_label, member, isProvisionedUser, variant) => {
        expect(waysToUseVariant(member, isProvisionedUser)).toBe(variant)
    })

    it.each([
        ['connected', [{ kind: 'slack' }], OrganizationMembershipLevel.Member, 'connected'],
        ['an admin can connect', [], OrganizationMembershipLevel.Admin, 'can_connect'],
        ['a member must ask an admin', [], OrganizationMembershipLevel.Member, 'ask_admin'],
        ['an unknown level must ask an admin', [], null, 'ask_admin'],
    ])('reports the Slack state when %s', (_label, integrations, level, state) => {
        expect(waysToUseSlackState(integrations as IntegrationType[], level)).toBe(state)
    })

    it('lists the team work once, dashboards first, without deleted items', () => {
        const items = teamWorkItems(
            [{ id: 1, name: 'Product health', description: '', team_id: 1, url: '/dashboard/1' }],
            [
                {
                    type: 'Dashboard',
                    actor_name: 'Theo Lind',
                    entity_name: 'Product health',
                    entity_url: '/dashboard/1',
                    timestamp: '2026-10-15T09:00:00Z',
                },
                {
                    type: 'Insight.deleted',
                    actor_name: 'Theo Lind',
                    entity_name: 'Old chart',
                    entity_url: '/insights/old',
                    timestamp: '2026-10-15T09:00:00Z',
                },
                {
                    type: 'Insight.created',
                    actor_name: 'Ana Ruiz',
                    entity_name: 'Signups',
                    entity_url: '/insights/new',
                    timestamp: '2026-10-15T09:00:00Z',
                },
            ]
        )
        expect(items.map((item) => [item.url, item.detail])).toEqual([
            ['/dashboard/1', 'Opened recently'],
            ['/insights/new', 'Created by Ana'],
        ])
    })

    it.each([
        ['an invitee with team context', 'invitee', true, ['team', 'surfaces']],
        ['an invitee in an empty organization', 'invitee', false, ['surfaces']],
        ['the organization creator', 'creator', true, ['surfaces']],
    ] as const)('gives %s the right steps', (_label, variant, hasTeamContent, steps) => {
        expect(waysToUseSteps(variant, hasTeamContent)).toEqual(steps)
    })

    describe('logic', () => {
        let logic: ReturnType<typeof waysToUseLogic.build>

        beforeEach(() => {
            jest.useFakeTimers({ now: NOW })
            initKeaTests()
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {
                [FEATURE_FLAGS.TODAY_RAIL_NAV]: true,
            })
            userLogic.mount()
            userLogic.actions.loadUserSuccess(user({ is_organization_first_user: true }))
            sceneLogic.mount()
            logic = waysToUseLogic()
            logic.mount()
            logic.actions.setIntegrations([])
            jest.runOnlyPendingTimers()
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        const openScene = (sceneKey: string): void => {
            sceneLogic.actions.setScene(Scene.ProjectHomepage, sceneKey, {
                params: {},
                searchParams: {},
                hashParams: {},
            })
        }

        it.each([
            ['opens on Today home', 'projectHomepage', true],
            ['stays closed over a Today report, which shares the home scene', 'todayReport', false],
        ])('%s', (_label, sceneKey, isOpen) => {
            openScene(sceneKey)
            expect(logic.values.isOpen).toBe(isOpen)
        })

        it('waits while the forced two-factor setup is open', () => {
            twoFactorLogic.actions.openTwoFactorSetupModal(true)
            openScene('projectHomepage')
            expect(logic.values.isOpen).toBe(false)
        })

        it('records the close against this organization and keeps it closed', async () => {
            openScene('projectHomepage')
            await expectLogic(logic, () => {
                logic.actions.closeWaysToUse('get_started')
            })
                .toDispatchActions([userLogic.actionCreators.updateHasSeenProductIntroFor(SEEN_KEY)])
                .toMatchValues({ closed: true, isOpen: false })
        })
    })
})
