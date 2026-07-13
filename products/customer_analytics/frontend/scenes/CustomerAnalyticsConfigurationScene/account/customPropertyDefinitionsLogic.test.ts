import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    CustomPropertyDefinitionApi,
    CustomPropertySourceApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { customPropertyDefinitionsLogic } from './customPropertyDefinitionsLogic'

const DEFINITIONS_URL = '/api/projects/:team_id/custom_property_definitions/'
const DEFINITION_URL = '/api/projects/:team_id/custom_property_definitions/:id/'
const SAVED_QUERIES_URL = '/api/environments/:team_id/warehouse_saved_queries/'
const SOURCES_URL = '/api/projects/:team_id/custom_property_sources/'
const SOURCE_URL = '/api/projects/:team_id/custom_property_sources/:id/'

const buildSource = (overrides: Partial<CustomPropertySourceApi> = {}): CustomPropertySourceApi =>
    ({
        id: 'src-1',
        definition: 'def-1',
        saved_query: 'view-1',
        source_column: 'mrr',
        key_column: 'org_id',
        is_enabled: true,
        consecutive_failures: 0,
        last_synced_at: '2026-01-02T00:00:00Z',
        last_sync_error: null,
        created_at: '2026-01-01T00:00:00Z',
        created_by: 1,
        updated_at: '2026-01-02T00:00:00Z',
        ...overrides,
    }) as CustomPropertySourceApi

const buildDefinition = (overrides: Partial<CustomPropertyDefinitionApi> = {}): CustomPropertyDefinitionApi =>
    ({
        id: 'def-1',
        name: 'ARR',
        description: null,
        display_type: 'currency',
        is_big_number: true,
        source: null,
        references: [],
        created_at: '2026-01-01T00:00:00Z',
        created_by: 1,
        updated_at: '2026-01-01T00:00:00Z',
        ...overrides,
    }) as CustomPropertyDefinitionApi

// Loosely-typed warehouse view — the logic only reads id/name/columns[].name/is_materialized.
const buildView = (overrides: Record<string, any> = {}): any => ({
    id: 'view-1',
    name: 'billing_view',
    columns: [{ name: 'org_id' }, { name: 'mrr' }],
    is_materialized: true,
    ...overrides,
})

const defaultMocks = (): Parameters<typeof useMocks>[0] => ({
    get: {
        [DEFINITIONS_URL]: { count: 1, results: [buildDefinition()] },
        [SAVED_QUERIES_URL]: { count: 1, results: [buildView()] },
    },
    post: {
        [DEFINITIONS_URL]: buildDefinition({ id: 'def-2' }),
        [SOURCES_URL]: buildSource(),
    },
    patch: { [DEFINITION_URL]: buildDefinition(), [SOURCE_URL]: buildSource() },
    delete: { [DEFINITION_URL]: {}, [SOURCE_URL]: {} },
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
        jest.spyOn(window, 'open').mockReturnValue(null)
    })

    afterEach(resumeKeaLoadersErrors)

    it('loads definitions on mount', async () => {
        useMocks(defaultMocks())
        mountLogic()
        await expectLogic(logic)
            .toDispatchActions(['loadDefinitions', 'loadDefinitionsSuccess'])
            .toMatchValues({ definitions: [expect.objectContaining({ id: 'def-1', name: 'ARR' })] })
    })

    it('hydrates the form, including the source fields, when editing a synced definition', async () => {
        useMocks(defaultMocks())
        mountLogic()
        const definition = buildDefinition({ source: buildSource() })
        await expectLogic(logic, () => logic.actions.openEditModal(definition))
            .toDispatchActions(['loadSavedQueries', 'loadSavedQueriesSuccess'])
            .toFinishAllListeners()

        expect(logic.values.modalVisible).toBe(true)
        expect(logic.values.editingDefinition).toEqual(definition)
        expect(logic.values.customPropertyForm).toEqual({
            name: 'ARR',
            description: '',
            displayType: 'currency',
            isBigNumber: true,
            options: [],
            sourceMode: 'data_warehouse',
            savedQuery: 'view-1',
            sourceColumn: 'mrr',
            keyColumn: 'org_id',
            isEnabled: true,
        })
    })

    it.each([
        [
            'workflow references',
            { references: [{ id: 'flow-1', name: 'Flow', status: 'draft', type: 'workflow' }] },
            'workflow',
        ],
        ['no source or references', {}, 'manual'],
    ] as [string, Partial<CustomPropertyDefinitionApi>, string][])(
        'derives the source mode when editing a definition with %s',
        async (_, overrides, expectedMode) => {
            useMocks(defaultMocks())
            mountLogic()
            await expectLogic(logic, () =>
                logic.actions.openEditModal(buildDefinition(overrides))
            ).toFinishAllListeners()
            expect(logic.values.customPropertyForm.sourceMode).toBe(expectedMode)
        }
    )

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
                ...defaultMocks().patch,
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

    it('treats an already-deleted definition (404) as a successful delete', async () => {
        silenceKeaLoadersErrors() // the 404 loader failure is the scenario under test
        useMocks({
            ...defaultMocks(),
            delete: { ...defaultMocks().delete, [DEFINITION_URL]: () => [404, { detail: 'Not found.' }] },
        })
        mountLogic()
        await expectLogic(logic).toDispatchActions(['loadDefinitionsSuccess'])
        // A 404 refreshes the table instead of surfacing a failure toast/exception.
        await expectLogic(logic, () => logic.actions.deleteDefinition({ id: 'def-1' })).toDispatchActions([
            'deleteDefinitionFailure',
            'loadDefinitions',
        ])
    })

    it('exposes the selected view columns for the pickers', async () => {
        useMocks(defaultMocks())
        mountLogic()
        await expectLogic(logic, () => logic.actions.openCreateModal()).toDispatchActions(['loadSavedQueriesSuccess'])
        logic.actions.setCustomPropertyFormValue('savedQuery', 'view-1')
        expect(logic.values.selectedSourceColumns).toEqual(['org_id', 'mrr'])
    })

    it('creates the definition and then its source when saving in data warehouse mode', async () => {
        let sourceBody: Record<string, any> | null = null
        useMocks({
            ...defaultMocks(),
            post: {
                ...defaultMocks().post,
                [SOURCES_URL]: async ({ request }) => {
                    sourceBody = (await request.json()) as Record<string, any>
                    return buildSource()
                },
            },
        })
        mountLogic()
        logic.actions.openCreateModal()
        logic.actions.setCustomPropertyFormValues({
            name: 'MRR',
            sourceMode: 'data_warehouse',
            savedQuery: 'view-1',
            sourceColumn: 'mrr',
            keyColumn: 'org_id',
            isEnabled: true,
        })

        await expectLogic(logic, () => logic.actions.submitCustomPropertyForm()).toDispatchActions([
            'setEditingDefinition',
            'submitCustomPropertyFormSuccess',
        ])
        // The source must be attached to the definition id returned by the create call.
        expect(sourceBody).toEqual({
            definition: 'def-2',
            saved_query: 'view-1',
            source_column: 'mrr',
            key_column: 'org_id',
            is_enabled: true,
        })
    })

    it('updates an existing source via PATCH without the create-only fields', async () => {
        let patchedBody: Record<string, any> | null = null
        useMocks({
            ...defaultMocks(),
            patch: {
                ...defaultMocks().patch,
                [SOURCE_URL]: async ({ request }) => {
                    patchedBody = (await request.json()) as Record<string, any>
                    return buildSource()
                },
            },
        })
        mountLogic()
        logic.actions.openEditModal(buildDefinition({ source: buildSource() }))
        logic.actions.setCustomPropertyFormValue('isEnabled', false)

        await expectLogic(logic, () => logic.actions.submitCustomPropertyForm()).toDispatchActions([
            'submitCustomPropertyFormSuccess',
        ])
        expect(patchedBody).toEqual({ source_column: 'mrr', key_column: 'org_id', is_enabled: false })
    })

    it('deletes the source when saving after switching away from data warehouse mode', async () => {
        let sourceDeleted = false
        useMocks({
            ...defaultMocks(),
            delete: {
                ...defaultMocks().delete,
                [SOURCE_URL]: () => {
                    sourceDeleted = true
                    return [204, null]
                },
            },
        })
        mountLogic()
        logic.actions.openEditModal(buildDefinition({ source: buildSource() }))
        logic.actions.setCustomPropertyFormValue('sourceMode', 'manual')

        await expectLogic(logic, () => logic.actions.submitCustomPropertyForm()).toDispatchActions([
            'submitCustomPropertyFormSuccess',
        ])
        expect(sourceDeleted).toBe(true)
    })

    it('fails the workflow CTA with a field error when the name is missing', async () => {
        silenceKeaLoadersErrors() // the MissingNameError loader failure is the scenario under test
        useMocks(defaultMocks())
        mountLogic()
        logic.actions.openCreateModal()

        await expectLogic(logic, () => logic.actions.createWorkflowForProperty()).toDispatchActions([
            'createWorkflowForPropertyFailure',
            'setCustomPropertyFormManualErrors',
        ])
        expect(window.open).not.toHaveBeenCalled()
    })

    it('creates the property and opens the new-workflow editor', async () => {
        useMocks(defaultMocks())
        mountLogic()
        logic.actions.openCreateModal()
        logic.actions.setCustomPropertyFormValues({ name: 'Health score', sourceMode: 'workflow' })

        await expectLogic(logic, () => logic.actions.createWorkflowForProperty()).toDispatchActions([
            // The definition must be created first — the workflow action references it by id.
            'setEditingDefinition',
            'createWorkflowForPropertySuccess',
        ])
        expect(window.open).toHaveBeenCalledWith('/workflows/new/workflow', '_blank')
    })

    it('opens the editor without re-creating an already-existing property', async () => {
        let definitionCreated = false
        useMocks({
            ...defaultMocks(),
            post: {
                ...defaultMocks().post,
                [DEFINITIONS_URL]: () => {
                    definitionCreated = true
                    return buildDefinition({ id: 'def-2' })
                },
            },
        })
        mountLogic()
        logic.actions.openEditModal(buildDefinition())

        await expectLogic(logic, () => logic.actions.createWorkflowForProperty()).toDispatchActions([
            'createWorkflowForPropertySuccess',
        ])
        expect(definitionCreated).toBe(false)
        expect(window.open).toHaveBeenCalledWith('/workflows/new/workflow', '_blank')
    })
})
