import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { AccountRelationshipDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { relationshipDefinitionsLogic } from './relationshipDefinitionsLogic'

const DEFINITIONS_URL = '/api/projects/:team_id/account_relationship_definitions/'
const DEFINITION_URL = '/api/projects/:team_id/account_relationship_definitions/:id/'

const buildDefinition = (
    overrides: Partial<AccountRelationshipDefinitionApi> = {}
): AccountRelationshipDefinitionApi => ({
    id: 'def-1',
    name: 'CSM',
    description: null,
    is_single_holder: true,
    ...overrides,
})

describe('relationshipDefinitionsLogic', () => {
    let logic: ReturnType<typeof relationshipDefinitionsLogic.build>

    const mountLogic = (): void => {
        logic = relationshipDefinitionsLogic()
        logic.mount()
    }

    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            current_team: MOCK_DEFAULT_TEAM,
            current_user: MOCK_DEFAULT_USER,
        } as any
        initKeaTests()
        userLogic.mount()
    })

    it('loads definitions on mount', async () => {
        useMocks({ get: { [DEFINITIONS_URL]: { count: 1, results: [buildDefinition()] } } })
        mountLogic()
        await expectLogic(logic)
            .toDispatchActions(['loadDefinitions', 'loadDefinitionsSuccess'])
            .toMatchValues({ definitions: [expect.objectContaining({ id: 'def-1', name: 'CSM' })] })
    })

    it('creates a definition and reloads the list', async () => {
        useMocks({
            get: { [DEFINITIONS_URL]: { count: 0, results: [] } },
            post: { [DEFINITIONS_URL]: buildDefinition({ id: 'def-2', name: 'FDE', is_single_holder: false }) },
        })
        mountLogic()
        logic.actions.openCreateModal()
        logic.actions.setRelationshipDefinitionFormValues({ name: 'FDE' })

        await expectLogic(logic, () => logic.actions.submitRelationshipDefinitionForm()).toDispatchActions([
            'submitRelationshipDefinitionFormSuccess',
            'loadDefinitions',
            'closeModal',
        ])
        expect(logic.values.modalVisible).toBe(false)
    })

    it('maps a 409 to a name form error and keeps the modal open', async () => {
        useMocks({
            get: { [DEFINITIONS_URL]: { count: 0, results: [] } },
            post: { [DEFINITIONS_URL]: () => [409, { detail: 'duplicate' }] },
        })
        mountLogic()
        logic.actions.openCreateModal()
        logic.actions.setRelationshipDefinitionFormValues({ name: 'CSM' })

        await expectLogic(logic, () => logic.actions.submitRelationshipDefinitionForm()).toDispatchActions([
            'submitRelationshipDefinitionFormFailure',
        ])
        expect(logic.values.modalVisible).toBe(true)
        expect(logic.values.relationshipDefinitionFormManualErrors).toEqual({
            name: 'A relationship with this name already exists.',
        })
    })

    it('hydrates the form when editing', async () => {
        useMocks({ get: { [DEFINITIONS_URL]: { count: 0, results: [] } } })
        mountLogic()
        const definition = buildDefinition({ description: 'Runs onboarding' })

        logic.actions.openEditModal(definition)

        expect(logic.values.editingDefinition).toEqual(definition)
        expect(logic.values.relationshipDefinitionForm).toEqual({
            name: 'CSM',
            description: 'Runs onboarding',
        })
    })

    it('removes a deleted definition from the list', async () => {
        useMocks({
            get: { [DEFINITIONS_URL]: { count: 1, results: [buildDefinition()] } },
            delete: { [DEFINITION_URL]: {} },
        })
        mountLogic()
        await expectLogic(logic).toDispatchActions(['loadDefinitionsSuccess'])

        await expectLogic(logic, () => logic.actions.deleteDefinition({ id: 'def-1' })).toDispatchActions([
            'deleteDefinitionSuccess',
        ])
        expect(logic.values.definitions).toEqual([])
    })
})
