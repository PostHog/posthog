import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'

import { initKeaTests } from '~/test/init'

import { AppContext, AvailableFeature, BillingFeatureType, OrganizationType } from '../types'
import { organizationLogic } from './organizationLogic'

describe('organizationLogic', () => {
    let logic: ReturnType<typeof organizationLogic.build>

    describe('if POSTHOG_APP_CONTEXT available', () => {
        beforeEach(() => {
            window.POSTHOG_APP_CONTEXT = { current_user: { organization: { id: 'WXYZ' } } } as unknown as AppContext
            initKeaTests()
            logic = organizationLogic()
            logic.mount()
        })

        it('loads organization from window', async () => {
            await expectLogic(logic).toNotHaveDispatchedActions(['loadCurrentOrganization'])
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])
            await expectLogic(logic).toMatchValues({
                currentOrganization: { id: 'WXYZ' },
            })
        })

        it('currentOrganizationId returns the id when loaded', async () => {
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])
            expect(logic.values.currentOrganizationId).toBe('WXYZ')
        })
    })

    describe('currentOrganizationId before load', () => {
        it('returns @current fallback when currentOrganization is null', () => {
            // Clear the user/organization context so currentOrganization starts as null
            window.POSTHOG_APP_CONTEXT = { current_user: null } as unknown as AppContext
            initKeaTests(false)
            logic = organizationLogic()
            logic.mount()
            expect(logic.values.currentOrganizationId).toBe('@current')
        })
    })

    describe('if POSTHOG_APP_CONTEXT is undefined', () => {
        // Should not happen in production, but the app should still not break.
        // We use initKeaTests(false) to set up the kea environment, then reset the context to undefined
        // so organizationLogic sees the real undefined case when it mounts.
        beforeEach(() => {
            initKeaTests(false)
            window.POSTHOG_APP_CONTEXT = undefined as unknown as AppContext
            logic = organizationLogic()
            logic.mount()
        })
        it('falls back to loading organization from API', async () => {
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganization', 'loadCurrentOrganizationSuccess'])
            await expectLogic(logic).toMatchValues({
                currentOrganization: { ...MOCK_DEFAULT_ORGANIZATION },
            })
        })
    })

    describe('projectCreationForbiddenReason', () => {
        const projectsFeature = (limit: number | null): BillingFeatureType => ({
            key: AvailableFeature.ORGANIZATIONS_PROJECTS,
            name: 'Projects',
            limit,
        })
        const teamsOfLength = (count: number): OrganizationType['teams'] =>
            Array.from({ length: count }, (_, index) => ({ ...MOCK_DEFAULT_TEAM, id: index + 1 }))
        const buildOrg = (overrides: Partial<OrganizationType>): OrganizationType => ({
            ...MOCK_DEFAULT_ORGANIZATION,
            ...overrides,
        })

        it.each<[string, OrganizationType, string | null]>([
            [
                'blocks an admin who reached the plan project limit',
                buildOrg({
                    membership_level: OrganizationMembershipLevel.Admin,
                    teams: teamsOfLength(1),
                    available_product_features: [projectsFeature(1)],
                }),
                'Your plan is limited to 1 project. Upgrade your plan to add more.',
            ],
            [
                'pluralizes the limit in the reason',
                buildOrg({
                    membership_level: OrganizationMembershipLevel.Admin,
                    teams: teamsOfLength(3),
                    available_product_features: [projectsFeature(3)],
                }),
                'Your plan is limited to 3 projects. Upgrade your plan to add more.',
            ],
            [
                'allows creation below the limit',
                buildOrg({
                    membership_level: OrganizationMembershipLevel.Admin,
                    teams: teamsOfLength(1),
                    available_product_features: [projectsFeature(6)],
                }),
                null,
            ],
            [
                'allows creation on an unlimited plan',
                buildOrg({
                    membership_level: OrganizationMembershipLevel.Admin,
                    teams: teamsOfLength(5),
                    available_product_features: [projectsFeature(null)],
                }),
                null,
            ],
            [
                'allows creation when the org has no projects entitlement',
                buildOrg({
                    membership_level: OrganizationMembershipLevel.Admin,
                    teams: teamsOfLength(1),
                    available_product_features: [],
                }),
                null,
            ],
            [
                'requires admin rights before the plan limit',
                buildOrg({
                    membership_level: OrganizationMembershipLevel.Member,
                    members_can_create_projects: false,
                    teams: teamsOfLength(1),
                    available_product_features: [projectsFeature(1)],
                }),
                'You need to be an organization admin or above to create new projects.',
            ],
        ])('%s', async (_description, organization, expected) => {
            initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, organization)
            logic = organizationLogic()
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])
            expect(logic.values.projectCreationForbiddenReason).toBe(expected)
        })
    })

    describe('if organization not in POSTHOG_APP_CONTEXT', () => {
        // In production POSTHOG_APP_CONTEXT is always present (server-rendered in posthog/templates/head.html),
        // but current_user is null for unauthenticated requests such as shared dashboards (see posthog/utils.py).
        // That is the real trigger for the async API load path.
        beforeEach(async () => {
            window.POSTHOG_APP_CONTEXT = { current_user: null } as unknown as AppContext
            initKeaTests()
            logic = organizationLogic()
            logic.mount()
        })
        it('loads organization from API', async () => {
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganization', 'loadCurrentOrganizationSuccess'])
            await expectLogic(logic).toMatchValues({
                currentOrganization: { ...MOCK_DEFAULT_ORGANIZATION },
            })
        })
    })
})
