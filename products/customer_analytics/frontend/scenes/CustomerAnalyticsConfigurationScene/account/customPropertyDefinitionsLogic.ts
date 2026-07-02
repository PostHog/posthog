import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import type { DataWarehouseSavedQuery } from '~/types'

import {
    customPropertyDefinitionsCreate,
    customPropertyDefinitionsDestroy,
    customPropertyDefinitionsList,
    customPropertyDefinitionsPartialUpdate,
    customPropertySourcesCreate,
    customPropertySourcesDestroy,
    customPropertySourcesPartialUpdate,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    CustomPropertyDefinitionApi,
    CustomPropertyDisplayTypeEnumApi,
    CustomPropertyReferenceApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import type { customPropertyDefinitionsLogicType } from './customPropertyDefinitionsLogicType'
import { isNumericDisplayType } from './customPropertyTypes'

export type CustomPropertySourceMode = 'manual' | 'data_warehouse' | 'workflow'

export interface CustomPropertyFormValues {
    name: string
    description: string
    displayType: CustomPropertyDisplayTypeEnumApi
    isBigNumber: boolean
    sourceMode: CustomPropertySourceMode
    savedQuery: string | null
    sourceColumn: string | null
    keyColumn: string | null
    isEnabled: boolean
}

const DEFAULT_FORM_VALUES: CustomPropertyFormValues = {
    name: '',
    description: '',
    displayType: 'text',
    isBigNumber: false,
    sourceMode: 'manual',
    savedQuery: null,
    sourceColumn: null,
    keyColumn: null,
    isEnabled: true,
}

export interface CustomPropertySourceFormValues {
    savedQuery: string | null
    sourceColumn: string | null
    keyColumn: string | null
    isEnabled: boolean
}

const DEFAULT_SOURCE_FORM_VALUES: CustomPropertySourceFormValues = {
    savedQuery: null,
    sourceColumn: null,
    keyColumn: null,
    isEnabled: true,
}

const serializeDefinition = ({
    name,
    description,
    displayType,
    isBigNumber,
}: CustomPropertyFormValues): {
    name: string
    description: string | null
    display_type: CustomPropertyDisplayTypeEnumApi
    is_big_number: boolean
} => ({
    name: name.trim(),
    description: description?.trim() || null,
    display_type: displayType,
    // The switch is hidden for non-numeric types, so never send a stale flag for them.
    is_big_number: isNumericDisplayType(displayType) ? isBigNumber : false,
})

const handleNameConflict = (error: unknown, setManualErrors: (errors: { name: string }) => void): boolean => {
    if ((error as { status?: number })?.status !== 409) {
        return false
    }
    setManualErrors({ name: 'A custom property with this name already exists.' })
    return true
}

class MissingNameError extends Error {}

export const customPropertyDefinitionsLogic = kea<customPropertyDefinitionsLogicType>([
    path([
        'products',
        'customer_analytics',
        'frontend',
        'scenes',
        'CustomerAnalyticsConfigurationScene',
        'account',
        'customPropertyDefinitionsLogic',
    ]),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        openCreateModal: true,
        openEditModal: (definition: CustomPropertyDefinitionApi) => ({ definition }),
        closeModal: true,
        setEditingDefinition: (definition: CustomPropertyDefinitionApi) => ({ definition }),
        openSourceModal: (definition: CustomPropertyDefinitionApi) => ({ definition }),
        closeSourceModal: true,
    }),
    reducers({
        modalVisible: [
            false,
            {
                openCreateModal: () => true,
                openEditModal: () => true,
                closeModal: () => false,
            },
        ],
        editingDefinition: [
            null as CustomPropertyDefinitionApi | null,
            {
                openCreateModal: () => null,
                openEditModal: (_, { definition }) => definition,
                setEditingDefinition: (_, { definition }) => definition,
                closeModal: () => null,
            },
        ],
        sourceModalVisible: [
            false,
            {
                openSourceModal: () => true,
                closeSourceModal: () => false,
            },
        ],
        sourceDefinition: [
            null as CustomPropertyDefinitionApi | null,
            {
                openSourceModal: (_, { definition }) => definition,
                closeSourceModal: () => null,
            },
        ],
    }),
    loaders(({ actions, values }) => ({
        definitions: [
            [] as CustomPropertyDefinitionApi[],
            {
                loadDefinitions: async (): Promise<CustomPropertyDefinitionApi[]> => {
                    const response = await customPropertyDefinitionsList(String(values.currentProjectId))
                    return response.results
                },
                deleteDefinition: async ({ id }: { id: string }): Promise<CustomPropertyDefinitionApi[]> => {
                    await customPropertyDefinitionsDestroy(String(values.currentProjectId), id)
                    return values.definitions.filter((definition) => definition.id !== id)
                },
                removeSource: async ({
                    definition,
                }: {
                    definition: CustomPropertyDefinitionApi
                }): Promise<CustomPropertyDefinitionApi[]> => {
                    if (definition.source) {
                        await customPropertySourcesDestroy(String(values.currentProjectId), definition.source.id)
                    }
                    // Re-fetch so the cleared `source` is reflected — it can't be derived locally.
                    const response = await customPropertyDefinitionsList(String(values.currentProjectId))
                    return response.results
                },
            },
        ],
        savedQueries: [
            [] as DataWarehouseSavedQuery[],
            {
                loadSavedQueries: async (): Promise<DataWarehouseSavedQuery[]> => {
                    const response = await api.dataWarehouseSavedQueries.list()
                    return response.results
                },
            },
        ],
        newWorkflowUrl: [
            null as string | null,
            {
                createWorkflowForProperty: async (): Promise<string> => {
                    const formValues = values.customPropertyForm
                    if (!formValues.name?.trim()) {
                        throw new MissingNameError()
                    }
                    // The property must exist first — the workflow action references it by id.
                    if (!values.editingDefinition) {
                        const definition = await customPropertyDefinitionsCreate(
                            String(values.currentProjectId),
                            serializeDefinition(formValues)
                        )
                        actions.setEditingDefinition(definition)
                        actions.loadDefinitions()
                    }
                    return urls.workflowNew()
                },
            },
        ],
    })),
    forms(({ actions, values }) => ({
        customPropertyForm: {
            defaults: DEFAULT_FORM_VALUES,
            errors: ({ name, sourceMode, savedQuery, sourceColumn, keyColumn }: CustomPropertyFormValues) => ({
                name: !name?.trim() ? 'Name is required' : undefined,
                savedQuery: sourceMode === 'data_warehouse' && !savedQuery ? 'Select a view' : undefined,
                sourceColumn: sourceMode === 'data_warehouse' && !sourceColumn ? 'Select the value column' : undefined,
                keyColumn: sourceMode === 'data_warehouse' && !keyColumn ? 'Select the key column' : undefined,
            }),
            submit: async (formValues: CustomPropertyFormValues) => {
                const projectId = String(values.currentProjectId)
                const editing = values.editingDefinition
                const body = serializeDefinition(formValues)
                let definition: CustomPropertyDefinitionApi
                if (editing) {
                    definition = await customPropertyDefinitionsPartialUpdate(projectId, editing.id, body)
                } else {
                    definition = await customPropertyDefinitionsCreate(projectId, body)
                    // Switch to edit mode right away so a failed source step below retries as an
                    // update instead of re-creating the definition (409).
                    actions.setEditingDefinition(definition)
                }
                try {
                    const { sourceMode, savedQuery, sourceColumn, keyColumn, isEnabled } = formValues
                    const existingSource = editing?.source ?? null
                    if (sourceMode === 'data_warehouse' && savedQuery && sourceColumn && keyColumn) {
                        if (existingSource) {
                            // saved_query is create-only — only the mutable fields are sent on update.
                            await customPropertySourcesPartialUpdate(projectId, existingSource.id, {
                                source_column: sourceColumn,
                                key_column: keyColumn,
                                is_enabled: isEnabled,
                            })
                        } else {
                            await customPropertySourcesCreate(projectId, {
                                definition: definition.id,
                                saved_query: savedQuery,
                                source_column: sourceColumn,
                                key_column: keyColumn,
                                is_enabled: isEnabled,
                            })
                        }
                    } else if (sourceMode !== 'data_warehouse' && existingSource) {
                        await customPropertySourcesDestroy(projectId, existingSource.id)
                    }
                } catch (error) {
                    throw Object.assign(error as Error, { sourceStep: true })
                }
            },
        },
        customPropertySourceForm: {
            defaults: DEFAULT_SOURCE_FORM_VALUES,
            errors: ({ savedQuery, sourceColumn, keyColumn }: CustomPropertySourceFormValues) => ({
                savedQuery: !savedQuery ? 'Select a view' : undefined,
                sourceColumn: !sourceColumn ? 'Select the value column' : undefined,
                keyColumn: !keyColumn ? 'Select the key column' : undefined,
            }),
            submit: async ({ savedQuery, sourceColumn, keyColumn, isEnabled }: CustomPropertySourceFormValues) => {
                const definition = values.sourceDefinition
                if (!definition || !savedQuery || !sourceColumn || !keyColumn) {
                    return
                }
                if (definition.source) {
                    // saved_query is create-only — only the mutable fields are sent on update.
                    await customPropertySourcesPartialUpdate(String(values.currentProjectId), definition.source.id, {
                        source_column: sourceColumn,
                        key_column: keyColumn,
                        is_enabled: isEnabled,
                    })
                } else {
                    await customPropertySourcesCreate(String(values.currentProjectId), {
                        definition: definition.id,
                        saved_query: savedQuery,
                        source_column: sourceColumn,
                        key_column: keyColumn,
                        is_enabled: isEnabled,
                    })
                }
            },
        },
    })),
    selectors({
        materializedViews: [
            (s) => [s.savedQueries],
            (savedQueries: DataWarehouseSavedQuery[]): DataWarehouseSavedQuery[] =>
                savedQueries.filter((query) => query.is_materialized),
        ],
        selectedSourceColumns: [
            (s) => [s.savedQueries, s.customPropertyForm],
            (savedQueries: DataWarehouseSavedQuery[], form: CustomPropertyFormValues): string[] => {
                const view = savedQueries.find((query) => query.id === form.savedQuery)
                return (view?.columns ?? []).map((column) => column.name)
            },
        ],
        sourceModalColumns: [
            (s) => [s.savedQueries, s.customPropertySourceForm],
            (savedQueries: DataWarehouseSavedQuery[], form: CustomPropertySourceFormValues): string[] => {
                const view = savedQueries.find((query) => query.id === form.savedQuery)
                return (view?.columns ?? []).map((column) => column.name)
            },
        ],
        editingReferences: [
            (s) => [s.definitions, s.editingDefinition],
            (
                definitions: CustomPropertyDefinitionApi[],
                editingDefinition: CustomPropertyDefinitionApi | null
            ): readonly CustomPropertyReferenceApi[] => {
                if (!editingDefinition) {
                    return []
                }
                const fresh = definitions.find((definition) => definition.id === editingDefinition.id)
                return fresh?.references ?? editingDefinition.references ?? []
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        openCreateModal: () => {
            actions.resetCustomPropertyForm()
            actions.loadSavedQueries()
        },
        openEditModal: ({ definition }) => {
            actions.loadSavedQueries()
            actions.setCustomPropertyFormValues({
                name: definition.name,
                description: definition.description ?? '',
                displayType: definition.display_type,
                isBigNumber: definition.is_big_number ?? false,
                sourceMode: definition.source
                    ? 'data_warehouse'
                    : definition.references?.length
                      ? 'workflow'
                      : 'manual',
                savedQuery: definition.source?.saved_query ?? null,
                sourceColumn: definition.source?.source_column ?? null,
                keyColumn: definition.source?.key_column ?? null,
                isEnabled: definition.source?.is_enabled ?? true,
            })
        },
        submitCustomPropertyFormSuccess: () => {
            lemonToast.success('Custom property saved')
            actions.loadDefinitions()
            actions.closeModal()
        },
        submitCustomPropertyFormFailure: ({ error }) => {
            if ((error as { sourceStep?: boolean })?.sourceStep) {
                posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.submit' })
                // The definition was saved — refresh the table and keep the modal open for a retry.
                actions.loadDefinitions()
                lemonToast.error('Property saved, but the sync configuration failed. Fix it and save again.')
                return
            }
            // A name conflict is expected validation feedback, not an exception worth capturing.
            if (handleNameConflict(error, actions.setCustomPropertyFormManualErrors)) {
                return
            }
            posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.submit' })
            lemonToast.error('Failed to save custom property')
        },
        deleteDefinitionSuccess: () => {
            lemonToast.success('Custom property deleted')
        },
        deleteDefinitionFailure: ({ error }) => {
            posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.delete' })
            lemonToast.error('Failed to delete custom property')
        },
        loadDefinitionsFailure: ({ error }) => {
            posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.load' })
            lemonToast.error('Failed to load custom properties')
        },
        openSourceModal: ({ definition }) => {
            actions.loadSavedQueries()
            if (definition.source) {
                actions.setCustomPropertySourceFormValues({
                    savedQuery: definition.source.saved_query,
                    sourceColumn: definition.source.source_column,
                    keyColumn: definition.source.key_column,
                    isEnabled: definition.source.is_enabled ?? true,
                })
            } else {
                actions.resetCustomPropertySourceForm()
            }
        },
        submitCustomPropertySourceFormSuccess: () => {
            lemonToast.success(values.sourceDefinition?.source ? 'Sync updated' : 'Sync configured')
            actions.loadDefinitions()
            actions.closeSourceModal()
        },
        submitCustomPropertySourceFormFailure: ({ error }) => {
            posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.submitSource' })
            lemonToast.error((error as { detail?: string })?.detail ?? 'Failed to save sync configuration')
        },
        removeSourceSuccess: () => {
            lemonToast.success('Sync removed')
            actions.closeSourceModal()
        },
        removeSourceFailure: ({ error }) => {
            posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.removeSource' })
            lemonToast.error('Failed to remove sync')
        },
        createWorkflowForPropertySuccess: ({ newWorkflowUrl }) => {
            if (newWorkflowUrl && window.open(newWorkflowUrl, '_blank')) {
                lemonToast.success('Workflow editor opened in a new tab — save the workflow there, then refresh')
            } else {
                lemonToast.error('Could not open a new tab — check your popup blocker')
            }
        },
        createWorkflowForPropertyFailure: ({ errorObject }) => {
            if (errorObject instanceof MissingNameError) {
                actions.setCustomPropertyFormManualErrors({ name: 'Name is required' })
                return
            }
            posthog.captureException(errorObject, { scope: 'customPropertyDefinitionsLogic.createWorkflow' })
            if (handleNameConflict(errorObject, actions.setCustomPropertyFormManualErrors)) {
                return
            }
            lemonToast.error('Failed to create workflow')
        },
        loadSavedQueriesFailure: ({ error }) => {
            posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.loadSavedQueries' })
            lemonToast.error('Failed to load data warehouse views')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDefinitions()
    }),
])
