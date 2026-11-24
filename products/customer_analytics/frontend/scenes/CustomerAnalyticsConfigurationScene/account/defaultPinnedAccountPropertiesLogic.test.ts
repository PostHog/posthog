import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import type { CustomerAnalyticsConfig } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import type {
    AccountRelationshipDefinitionApi,
    CustomPropertyDefinitionApi,
    PinnedAccountPropertyApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { defaultPinnedAccountPropertiesLogic } from './defaultPinnedAccountPropertiesLogic'

const CUSTOM_PROPERTIES_URL = '/api/projects/:team_id/custom_property_definitions/'
const RELATIONSHIPS_URL = '/api/projects/:team_id/account_relationship_definitions/'
const ROLES_URL = '/api/organizations/:organization_id/roles/'
const TEAM_URL = '/api/environments/:team_id/'

interface TeamUpdateBody {
    customer_analytics_config: {
        default_pinned_properties?: PinnedAccountPropertyApi[]
        role_default_pinned_properties?: { role_id: string; pinned_properties: PinnedAccountPropertyApi[] }[]
    }
}

const customProperty = {
    id: 'custom-1',
    name: 'Annual recurring revenue',
    description: null,
    display_type: 'currency',
    target_type: 'account',
    is_big_number: false,
    is_canonical: false,
    options: null,
    source: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: 1,
    updated_at: '2026-01-01T00:00:00Z',
    references: [],
    has_workflow_reference: false,
} as CustomPropertyDefinitionApi

const relationship: AccountRelationshipDefinitionApi = {
    id: 'relationship-1',
    name: 'Customer success manager',
    description: null,
    is_single_holder: true,
    is_controlled: false,
}

describe('defaultPinnedAccountPropertiesLogic', () => {
    const logic = defaultPinnedAccountPropertiesLogic()

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic.unmount()
        teamLogic.unmount()
        resumeKeaLoadersErrors()
    })

    it('loads, cleans stale references, saves order, clears defaults, and saves one role without touching others', async () => {
        const submittedBodies: TeamUpdateBody[] = []
        let storedCustomerAnalyticsConfig: CustomerAnalyticsConfig = {
            ...MOCK_DEFAULT_TEAM.customer_analytics_config,
            default_pinned_properties: [
                { kind: 'custom_property', id: customProperty.id },
                { kind: 'custom_property', id: 'missing' },
            ],
            role_default_pinned_properties: [
                { role_id: 'role-other', pinned_properties: [{ kind: 'relationship', id: relationship.id }] },
                {
                    role_id: 'role-deleted',
                    pinned_properties: [{ kind: 'custom_property', id: customProperty.id }],
                },
                { role_id: 'role-csm', pinned_properties: [] },
            ],
        }
        useMocks({
            get: {
                [CUSTOM_PROPERTIES_URL]: { count: 1, results: [customProperty] },
                [RELATIONSHIPS_URL]: { count: 1, results: [relationship] },
                [ROLES_URL]: {
                    count: 2,
                    results: [
                        { id: 'role-other', name: 'Other' },
                        { id: 'role-csm', name: 'CSM' },
                    ],
                },
            },
            patch: {
                [TEAM_URL]: async ({ request }) => {
                    const body = (await request.json()) as TeamUpdateBody
                    submittedBodies.push(body)
                    storedCustomerAnalyticsConfig = {
                        ...storedCustomerAnalyticsConfig,
                        ...body.customer_analytics_config,
                    }
                    return {
                        ...MOCK_DEFAULT_TEAM,
                        customer_analytics_config: storedCustomerAnalyticsConfig,
                    }
                },
            },
        })
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            customer_analytics_config: storedCustomerAnalyticsConfig,
        })
        logic.mount()

        await waitFor(() => expect(logic.values.definitionsLoading).toBe(false))
        await waitFor(() => expect(logic.values.roles).toHaveLength(2))

        expect(logic.values.stalePinnedProperties).toEqual([{ kind: 'custom_property', id: 'missing' }])
        logic.actions.openConfigurator()
        expect(logic.values.draftPinnedPropertyKeys).toEqual(['custom:custom-1'])
        logic.actions.setDraftPinnedPropertyKeys(['relationship:relationship-1', 'custom:custom-1'])

        await expectLogic(logic, () => logic.actions.saveDefaultPinnedProperties())
            .toDispatchActions(['saveDefaultPinnedPropertiesSuccess'])
            .toFinishAllListeners()

        expect(submittedBodies[0]).toEqual({
            customer_analytics_config: {
                default_pinned_properties: [
                    { kind: 'relationship', id: relationship.id },
                    { kind: 'custom_property', id: customProperty.id },
                ],
            },
        })
        expect(logic.values.isOpen).toBe(false)

        logic.actions.openConfigurator()
        logic.actions.setDraftPinnedPropertyKeys([])
        await expectLogic(logic, () => logic.actions.saveDefaultPinnedProperties())
            .toDispatchActions(['saveDefaultPinnedPropertiesSuccess'])
            .toFinishAllListeners()

        expect(submittedBodies[1]).toEqual({
            customer_analytics_config: { default_pinned_properties: [] },
        })

        logic.actions.setSelectedRoleId('role-csm')
        logic.actions.openConfigurator()
        logic.actions.setDraftPinnedPropertyKeys(['custom:custom-1'])
        await expectLogic(logic, () => logic.actions.saveDefaultPinnedProperties())
            .toDispatchActions(['saveDefaultPinnedPropertiesSuccess'])
            .toFinishAllListeners()

        expect(submittedBodies[2]).toEqual({
            customer_analytics_config: {
                role_default_pinned_properties: [
                    { role_id: 'role-other', pinned_properties: [{ kind: 'relationship', id: relationship.id }] },
                    { role_id: 'role-csm', pinned_properties: [{ kind: 'custom_property', id: customProperty.id }] },
                ],
            },
        })
    })

    it('blocks changes when available definitions fail to load', async () => {
        silenceKeaLoadersErrors()
        useMocks({
            get: {
                [CUSTOM_PROPERTIES_URL]: () => [500, { detail: 'Could not load custom properties.' }],
                [RELATIONSHIPS_URL]: { count: 0, results: [] },
            },
        })
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            customer_analytics_config: {
                ...MOCK_DEFAULT_TEAM.customer_analytics_config,
                default_pinned_properties: [{ kind: 'custom_property', id: customProperty.id }],
            },
        })
        logic.mount()

        await waitFor(() => expect(logic.values.definitionsLoadFailed).toBe(true))
        logic.actions.openConfigurator()
        logic.actions.setDraftPinnedPropertyKeys([])

        expect(logic.values.canSave).toBe(false)
    })

    it.each([
        {
            name: 'loads every role page (>100 roles), preserves later-page role defaults, and drops deleted roles',
            page2Fails: false,
            expectedRolesCount: 101,
            expectedRoleIds: ['role-101', 'role-1'],
        },
        {
            name: 'preserves existing role defaults when role pagination fails before completing',
            page2Fails: true,
            expectedRolesCount: 0,
            expectedRoleIds: ['role-101', 'role-deleted', 'role-1'],
        },
    ])('$name', async ({ page2Fails, expectedRolesCount, expectedRoleIds }) => {
        if (page2Fails) {
            silenceKeaLoadersErrors()
        }
        const firstPageRoles = Array.from({ length: 100 }, (_, index) => ({
            id: `role-${index + 1}`,
            name: `Role ${index + 1}`,
        }))
        const secondPageRole = { id: 'role-101', name: 'Role 101' }
        const submittedBodies: TeamUpdateBody[] = []
        let storedCustomerAnalyticsConfig: CustomerAnalyticsConfig = {
            ...MOCK_DEFAULT_TEAM.customer_analytics_config,
            role_default_pinned_properties: [
                { role_id: 'role-1', pinned_properties: [{ kind: 'account_field', id: 'stripe_customer_id' }] },
                { role_id: 'role-101', pinned_properties: [{ kind: 'account_field', id: 'stripe_customer_id' }] },
                { role_id: 'role-deleted', pinned_properties: [{ kind: 'custom_property', id: customProperty.id }] },
            ],
        }
        useMocks({
            get: {
                [CUSTOM_PROPERTIES_URL]: { count: 1, results: [customProperty] },
                [RELATIONSHIPS_URL]: { count: 1, results: [relationship] },
                [ROLES_URL]: ({ request }) => {
                    const offset = Number(new URL(request.url).searchParams.get('offset') ?? '0')
                    if (offset === 0) {
                        return {
                            count: 101,
                            next: '/api/organizations/ABCD/roles/?offset=100',
                            results: firstPageRoles,
                        }
                    }
                    if (page2Fails) {
                        return [500, { detail: 'Could not load roles.' }]
                    }
                    return { count: 101, next: null, results: [secondPageRole] }
                },
            },
            patch: {
                [TEAM_URL]: async ({ request }) => {
                    const body = (await request.json()) as TeamUpdateBody
                    submittedBodies.push(body)
                    storedCustomerAnalyticsConfig = {
                        ...storedCustomerAnalyticsConfig,
                        ...body.customer_analytics_config,
                    }
                    return { ...MOCK_DEFAULT_TEAM, customer_analytics_config: storedCustomerAnalyticsConfig }
                },
            },
        })
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            customer_analytics_config: storedCustomerAnalyticsConfig,
        })
        logic.mount()

        await waitFor(() => expect(logic.values.definitionsLoading).toBe(false))
        await waitFor(() => expect(logic.values.rolesLoading).toBe(false))

        expect(logic.values.roles).toHaveLength(expectedRolesCount)
        expect(logic.values.rolesLoadedComplete).toBe(!page2Fails)

        logic.actions.setSelectedRoleId('role-1')
        logic.actions.openConfigurator()
        logic.actions.setDraftPinnedPropertyKeys(['custom:custom-1'])
        await expectLogic(logic, () => logic.actions.saveDefaultPinnedProperties())
            .toDispatchActions(['saveDefaultPinnedPropertiesSuccess'])
            .toFinishAllListeners()

        expect(
            submittedBodies[0].customer_analytics_config.role_default_pinned_properties?.map(({ role_id }) => role_id)
        ).toEqual(expectedRoleIds)
    })
})
