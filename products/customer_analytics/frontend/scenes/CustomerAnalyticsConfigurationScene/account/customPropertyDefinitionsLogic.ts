import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { projectLogic } from 'scenes/projectLogic'

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
} from 'products/customer_analytics/frontend/generated/api.schemas'

import type { customPropertyDefinitionsLogicType } from './customPropertyDefinitionsLogicType'
import { isNumericDisplayType } from './customPropertyTypes'

export interface CustomPropertyFormValues {
    name: string
    description: string
    displayType: CustomPropertyDisplayTypeEnumApi
    isBigNumber: boolean
}

const DEFAULT_FORM_VALUES: CustomPropertyFormValues = {
    name: '',
    description: '',
    displayType: 'text',
    isBigNumber: false,
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
    loaders(({ values }) => ({
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
    })),
    forms(({ values }) => ({
        customPropertyForm: {
            defaults: DEFAULT_FORM_VALUES,
            errors: ({ name }: CustomPropertyFormValues) => ({
                name: !name?.trim() ? 'Name is required' : undefined,
            }),
            submit: async ({ name, description, displayType, isBigNumber }: CustomPropertyFormValues) => {
                const body = {
                    name: name.trim(),
                    description: description?.trim() || null,
                    display_type: displayType,
                    // The switch is hidden for non-numeric types, so never send a stale flag for them.
                    is_big_number: isNumericDisplayType(displayType) ? isBigNumber : false,
                }
                const editing = values.editingDefinition
                if (editing) {
                    await customPropertyDefinitionsPartialUpdate(String(values.currentProjectId), editing.id, body)
                } else {
                    await customPropertyDefinitionsCreate(String(values.currentProjectId), body)
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
            (s) => [s.savedQueries, s.customPropertySourceForm],
            (savedQueries: DataWarehouseSavedQuery[], form: CustomPropertySourceFormValues): string[] => {
                const view = savedQueries.find((query) => query.id === form.savedQuery)
                return (view?.columns ?? []).map((column) => column.name)
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        openCreateModal: () => {
            actions.resetCustomPropertyForm()
        },
        openEditModal: ({ definition }) => {
            actions.setCustomPropertyFormValues({
                name: definition.name,
                description: definition.description ?? '',
                displayType: definition.display_type,
                isBigNumber: definition.is_big_number ?? false,
            })
        },
        submitCustomPropertyFormSuccess: () => {
            lemonToast.success(values.editingDefinition ? 'Custom property updated' : 'Custom property created')
            actions.loadDefinitions()
            actions.closeModal()
        },
        submitCustomPropertyFormFailure: ({ error }) => {
            posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.submit' })
            if ((error as { status?: number })?.status === 409) {
                actions.setCustomPropertyFormManualErrors({
                    name: 'A custom property with this name already exists.',
                })
                return
            }
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
        loadSavedQueriesFailure: ({ error }) => {
            posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.loadSavedQueries' })
            lemonToast.error('Failed to load data warehouse views')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDefinitions()
    }),
])
