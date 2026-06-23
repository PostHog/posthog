import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { customPropertyDefinitionsLogic } from './customPropertyDefinitionsLogic'

const DEFINITIONS_URL = '/api/projects/:team_id/custom_property_definitions/'
const DEFINITION_URL = '/api/projects/:team_id/custom_property_definitions/:id/'

const buildDefinition = (overrides: Partial<CustomPropertyDefinitionApi> = {}): CustomPropertyDefinitionApi =>
    ({
        id: 'def-1',
        name: 'ARR',
        description: null,
        display_type: 'currency',
        is_big_number: true,
        created_at: '2026-01-01T00:00:00Z',
        created_by: 1,
        updated_at: '2026-01-01T00:00:00Z',
        ...overrides,
    }) as CustomPropertyDefinitionApi

const defaultMocks = (): Parameters<typeof useMocks>[0] => ({
    get: { [DEFINITIONS_URL]: { count: 1, results: [buildDefinition()] } },
    post: { [DEFINITIONS_URL]: buildDefinition({ id: 'def-2' }) },
    patch: { [DEFINITION_URL]: buildDefinition() },
    delete: { [DEFINITION_URL]: {} },
})

describe('customPropertyDefinitionsLogic', () => {
    let logic: ReturnType<typeof customPropertyDefinitionsLogic.build>

    const mountLogic = (): void => {
        logic = customPropertyDefinitionsLogic()
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
        useMocks(defaultMocks())
        mountLogic()
        await expectLogic(logic)
            .toDispatchActions(['loadDefinitions', 'loadDefinitionsSuccess'])
            .toMatchValues({ definitions: [expect.objectContaining({ id: 'def-1', name: 'ARR' })] })
    })

    it('hydrates the form when editing a definition', async () => {
        useMocks(defaultMocks())
        mountLogic()
        const definition = buildDefinition()
        await expectLogic(logic, () => logic.actions.openEditModal(definition)).toFinishAllListeners()

        expect(logic.values.modalVisible).toBe(true)
        expect(logic.values.editingDefinition).toEqual(definition)
        expect(logic.values.customPropertyForm).toEqual({
            name: 'ARR',
            description: '',
            displayType: 'currency',
            isBigNumber: true,
        })
    })

    it('creates a definition, reloads, and closes the modal', async () => {
        useMocks(defaultMocks())
        mountLogic()
        logic.actions.openCreateModal()
        logic.actions.setCustomPropertyFormValues({
            name: 'Plan',
            description: '',
            displayType: 'text',
            isBigNumber: false,
        })

        await expectLogic(logic, () => logic.actions.submitCustomPropertyForm()).toDispatchActions([
            'submitCustomPropertyFormSuccess',
            'loadDefinitions',
            'closeModal',
        ])
        expect(logic.values.modalVisible).toBe(false)
    })

    it('drops the big-number flag when switching to a non-numeric type', async () => {
        let patchedBody: Record<string, any> | null = null
        useMocks({
            ...defaultMocks(),
            patch: {
                [DEFINITION_URL]: async ({ request }) => {
                    patchedBody = (await request.json()) as Record<string, any>
                    return buildDefinition()
                },
            },
        })
        mountLogic()
        // Edit a numeric definition that has the big-number flag on, then switch it to a
        // non-numeric type without touching the (now hidden) switch.
        logic.actions.openEditModal(buildDefinition({ display_type: 'currency', is_big_number: true }))
        logic.actions.setCustomPropertyFormValue('displayType', 'text')

        await expectLogic(logic, () => logic.actions.submitCustomPropertyForm()).toDispatchActions([
            'submitCustomPropertyFormSuccess',
        ])
        expect(patchedBody).toMatchObject({ display_type: 'text', is_big_number: false })
    })

    it('surfaces a name conflict on the name field', async () => {
        useMocks({ ...defaultMocks(), post: { [DEFINITIONS_URL]: () => [409, { detail: 'conflict' }] } })
        mountLogic()
        logic.actions.openCreateModal()
        logic.actions.setCustomPropertyFormValues({
            name: 'ARR',
            description: '',
            displayType: 'text',
            isBigNumber: false,
        })

        await expectLogic(logic, () => logic.actions.submitCustomPropertyForm()).toDispatchActions([
            'submitCustomPropertyFormFailure',
            'setCustomPropertyFormManualErrors',
        ])
        expect(logic.values.modalVisible).toBe(true)
    })

    it('deletes a definition', async () => {
        useMocks(defaultMocks())
        mountLogic()
        await expectLogic(logic).toDispatchActions(['loadDefinitionsSuccess'])
        await expectLogic(logic, () => logic.actions.deleteDefinition({ id: 'def-1' }))
            .toDispatchActions(['deleteDefinitionSuccess'])
            .toMatchValues({ definitions: [] })
    })
})
