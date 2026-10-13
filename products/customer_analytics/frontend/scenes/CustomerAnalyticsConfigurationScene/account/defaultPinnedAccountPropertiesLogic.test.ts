import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    AccountRelationshipDefinitionApi,
    CustomPropertyDefinitionApi,
    PinnedAccountPropertyApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { defaultPinnedAccountPropertiesLogic } from './defaultPinnedAccountPropertiesLogic'

const CUSTOM_PROPERTIES_URL = '/api/projects/:team_id/custom_property_definitions/'
const RELATIONSHIPS_URL = '/api/projects/:team_id/account_relationship_definitions/'
const TEAM_URL = '/api/environments/:team_id/'

interface TeamUpdateBody {
    customer_analytics_config: {
        default_pinned_properties: PinnedAccountPropertyApi[]
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

    it('loads, cleans stale references, saves order, and clears defaults', async () => {
        const submittedBodies: TeamUpdateBody[] = []
        useMocks({
            get: {
                [CUSTOM_PROPERTIES_URL]: { count: 1, results: [customProperty] },
                [RELATIONSHIPS_URL]: { count: 1, results: [relationship] },
            },
            patch: {
                [TEAM_URL]: async ({ request }) => {
                    const body = (await request.json()) as TeamUpdateBody
                    submittedBodies.push(body)
                    return {
                        ...MOCK_DEFAULT_TEAM,
                        customer_analytics_config: {
                            ...MOCK_DEFAULT_TEAM.customer_analytics_config,
                            ...body.customer_analytics_config,
                        },
                    }
                },
            },
        })
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            customer_analytics_config: {
                ...MOCK_DEFAULT_TEAM.customer_analytics_config,
                default_pinned_properties: [
                    { kind: 'custom_property', id: customProperty.id },
                    { kind: 'custom_property', id: 'missing' },
                ],
            },
        })
        logic.mount()

        await waitFor(() => expect(logic.values.definitionsLoading).toBe(false))

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
})
