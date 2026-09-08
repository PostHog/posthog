import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { userHasAccess } from 'lib/utils/accessControlUtils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    AccountRelationshipApi,
    AccountRelationshipDefinitionApi,
    CustomPropertyDefinitionApi,
    CustomPropertyValueWriteApi,
    AccountRelationshipWriteApi,
} from '../../generated/api.schemas'
import { accountSidebarPropertiesLogic } from './accountSidebarPropertiesLogic'

jest.mock('lib/utils/accessControlUtils', () => ({ userHasAccess: jest.fn(() => true) }))

const definition: CustomPropertyDefinitionApi = {
    id: 'property-1',
    name: 'Plan',
    display_type: 'text',
    target_type: 'account',
    is_canonical: false,
    source: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: 1,
    updated_at: null,
    references: [],
    has_workflow_reference: false,
}
const relationshipDefinition: AccountRelationshipDefinitionApi = {
    id: 'relationship-1',
    name: 'Account team',
    is_single_holder: false,
}
const VALUES_URL = '/api/projects/:project_id/accounts/:account_id/custom_property_values/'
const RELATIONSHIPS_URL = '/api/projects/:project_id/accounts/:account_id/relationships/'

describe('accountSidebarPropertiesLogic', () => {
    let logic: ReturnType<typeof accountSidebarPropertiesLogic.build>
    let storedValue: string | number | boolean | null
    let assignments: AccountRelationshipApi[]

    const assignment = (id: number, definition = relationshipDefinition): AccountRelationshipApi => ({
        id: `assignment-${id}`,
        definition,
        user: { id, email: `member${id}@example.com` },
        started_at: '2026-01-01T00:00:00Z',
        ended_at: null,
    })
    const mount = async (): Promise<void> => {
        logic = accountSidebarPropertiesLogic({ projectId: 1, accountId: 'account-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        await waitFor(() => expect(logic.values.sidebarProperties).toHaveLength(2))
    }

    beforeEach(() => {
        initKeaTests()
        storedValue = 'Starter'
        assignments = [assignment(1), assignment(2), assignment(3, { ...relationshipDefinition, id: 'other-role' })]
        useMocks({
            get: {
                '/api/projects/:project_id/user_customer_analytics_config/@me/': {
                    pinned_properties: [
                        { kind: 'relationship', id: relationshipDefinition.id },
                        { kind: 'custom_property', id: definition.id },
                    ],
                },
                '/api/projects/:project_id/custom_property_definitions/': { count: 1, results: [definition] },
                '/api/projects/:project_id/account_relationship_definitions/': {
                    count: 1,
                    results: [relationshipDefinition],
                },
                [VALUES_URL]: ({ params }) =>
                    storedValue === null
                        ? []
                        : [
                              {
                                  id: 'value-1',
                                  definition_id: definition.id,
                                  account_id: params.account_id,
                                  value: params.account_id === 'account-2' ? 'Other account' : storedValue,
                                  created_at: '2026-01-01T00:00:00Z',
                                  created_by_id: 1,
                              },
                          ],
                [RELATIONSHIPS_URL]: () => assignments,
            },
            post: {
                [VALUES_URL]: async ({ request }) => {
                    const body = (await request.json()) as CustomPropertyValueWriteApi
                    storedValue = body.value
                    return storedValue === null
                        ? [204, null]
                        : [201, { id: 'new-value', definition_id: body.definition, value: storedValue }]
                },
                [RELATIONSHIPS_URL]: async ({ request }) => {
                    const body = (await request.json()) as AccountRelationshipWriteApi
                    const next = assignment(body.user)
                    assignments.push(next)
                    return [201, next]
                },
                '/api/projects/:project_id/accounts/:account_id/relationships/:id/end/': ({ params }) => {
                    assignments = assignments.map((row) =>
                        row.id === params.id ? { ...row, ended_at: '2026-01-02T00:00:00Z' } : row
                    )
                    return assignments.find((row) => row.id === params.id)!
                },
            },
        })
    })

    afterEach(() => {
        logic?.unmount()
        resumeKeaLoadersErrors()
        jest.clearAllMocks()
    })

    it.each([
        ['text', 'Growth'],
        ['number', 0],
        ['boolean', false],
        ['clear', null],
    ])('saves %s values and reloads the row', async (_, value) => {
        await mount()
        const property = logic.values.sidebarProperties[1]
        logic.actions.editProperty(property)
        await expectLogic(logic, () => logic.actions.saveCustomProperty(property.key, value))
            .toFinishAllListeners()
            .toMatchValues({ editingPropertyKey: null, savingPropertyKey: null })
        expect(storedValue).toBe(value)
        expect(logic.values.sidebarProperties[1]).toMatchObject({ value })
    })

    it('keeps the editor and existing value after a failed save', async () => {
        silenceKeaLoadersErrors()
        useMocks({ post: { [VALUES_URL]: () => [400, { detail: 'Invalid value' }] } })
        await mount()
        logic.actions.editProperty(logic.values.sidebarProperties[1])
        await expectLogic(logic, () => logic.actions.saveCustomProperty('custom:property-1', 'invalid'))
            .toFinishAllListeners()
            .toMatchValues({
                editingPropertyKey: 'custom:property-1',
                savingPropertyKey: null,
                propertySaveFailed: true,
            })
        expect(logic.values.sidebarProperties[1]).toMatchObject({ value: 'Starter' })
    })

    it('replaces a multi-holder selection without ending retained or unrelated assignments', async () => {
        await mount()
        await expectLogic(logic, () =>
            logic.actions.saveRelationship('relationship:relationship-1', [2, 4])
        ).toFinishAllListeners()
        expect(
            assignments
                .filter((row) => !row.ended_at)
                .map((row) => row.user?.id)
                .sort()
        ).toEqual([2, 3, 4])
        expect(logic.values.sidebarProperties[0]).toMatchObject({ members: [{ id: 2 }, { id: 4 }] })
        await expectLogic(logic, () =>
            logic.actions.saveRelationship('relationship:relationship-1', [])
        ).toFinishAllListeners()
        expect(assignments.filter((row) => !row.ended_at).map((row) => row.user?.id)).toEqual([3])
        expect(assignments).toHaveLength(4)
    })

    it('keeps the draft after a partial relationship failure and retries without duplicate assignments', async () => {
        silenceKeaLoadersErrors()
        let fail = true
        useMocks({
            post: {
                [RELATIONSHIPS_URL]: async ({ request }) => {
                    const { user } = (await request.json()) as AccountRelationshipWriteApi
                    if (user === 5 && fail) {
                        return [500, { detail: 'Try again' }]
                    }
                    const row = assignment(user)
                    assignments.push(row)
                    return [201, row]
                },
            },
        })
        await mount()
        logic.actions.editProperty(logic.values.sidebarProperties[0])
        await expectLogic(logic, () => logic.actions.saveRelationship('relationship:relationship-1', [2, 4, 5]))
            .toFinishAllListeners()
            .toMatchValues({ propertySaveFailed: true, editingPropertyKey: 'relationship:relationship-1' })
        expect(logic.values.sidebarProperties[0]).toMatchObject({ members: [{ id: 1 }, { id: 2 }, { id: 4 }] })
        fail = false
        await expectLogic(logic, () => logic.actions.saveRelationship('relationship:relationship-1', [2, 4, 5]))
            .toFinishAllListeners()
            .toMatchValues({ propertySaveFailed: false, editingPropertyKey: null })
        expect(assignments.filter((row) => row.user?.id === 4)).toHaveLength(1)
        expect(logic.values.sidebarProperties[0]).toMatchObject({ members: [{ id: 2 }, { id: 4 }, { id: 5 }] })
    })

    it('lets the server end the previous single-holder assignment when replacing it', async () => {
        const single = { ...relationshipDefinition, is_single_holder: true }
        assignments = [assignment(1, single)]
        const endRequest = jest.fn(() => [409, { detail: 'Already ended' }])
        useMocks({
            get: { '/api/projects/:project_id/account_relationship_definitions/': { count: 1, results: [single] } },
            post: {
                [RELATIONSHIPS_URL]: async ({ request }) => {
                    const { user } = (await request.json()) as AccountRelationshipWriteApi
                    assignments = assignments.map((row) => ({ ...row, ended_at: '2026-01-02T00:00:00Z' }))
                    const row = assignment(user, single)
                    assignments.push(row)
                    return [201, row]
                },
                '/api/projects/:project_id/accounts/:account_id/relationships/:id/end/': endRequest,
            },
        })
        await mount()
        await expectLogic(logic, () =>
            logic.actions.saveRelationship('relationship:relationship-1', [2, 3])
        ).toFinishAllListeners()
        expect(assignments).toHaveLength(1)
        await expectLogic(logic, () => logic.actions.saveRelationship('relationship:relationship-1', [2]))
            .toFinishAllListeners()
            .toMatchValues({ propertySaveFailed: false })
        expect(logic.values.sidebarProperties[0]).toMatchObject({ members: [{ id: 2 }] })
        expect(assignments).toHaveLength(2)
        expect(endRequest).not.toHaveBeenCalled()
    })

    it('does not edit or save properties without resource-level editor access', async () => {
        jest.mocked(userHasAccess).mockReturnValueOnce(false)
        await mount()
        const write = jest.fn()
        useMocks({ post: { [VALUES_URL]: write, [RELATIONSHIPS_URL]: write } })
        for (const property of logic.values.sidebarProperties) {
            expect(property.editable).toBe(false)
            logic.actions.editProperty(property)
        }
        await expectLogic(logic, () => {
            logic.actions.saveCustomProperty('custom:property-1', 'blocked')
            logic.actions.saveRelationship('relationship:relationship-1', [4])
        }).toFinishAllListeners()
        expect(logic.values.editingPropertyKey).toBeNull()
        expect(write).not.toHaveBeenCalled()
    })

    it('does not show another account values while loading', async () => {
        await mount()
        const other = accountSidebarPropertiesLogic({ projectId: 1, accountId: 'account-2' })
        other.mount()
        try {
            expect(other.values.sidebarProperties).toEqual([])
            await expectLogic(other).toFinishAllListeners()
            expect(other.values.sidebarProperties[1]).toMatchObject({ value: 'Other account' })
            expect(logic.values.sidebarProperties[1]).toMatchObject({ value: 'Starter' })
        } finally {
            other.unmount()
        }
    })

    it.each([
        ['canonical', { is_canonical: true }],
        ['warehouse', { source: { id: 'source-1' } }],
        ['workflow', { has_workflow_reference: true }],
    ])('resolves %s provenance and restricts editing', async (provenance, overrides) => {
        useMocks({
            get: {
                '/api/projects/:project_id/custom_property_definitions/': {
                    count: 1,
                    results: [{ ...definition, ...overrides }],
                },
            },
        })
        await mount()
        const property = logic.values.sidebarProperties[1]
        expect(property).toMatchObject({ provenance })
        logic.actions.editProperty(property)
        expect(logic.values.editingPropertyKey).toBe(provenance === 'workflow' ? property.key : null)
        await expectLogic(logic, () => logic.actions.saveCustomProperty(property.key, 'Updated')).toFinishAllListeners()
        expect(storedValue).toBe(provenance === 'workflow' ? 'Updated' : 'Starter')
    })
})
