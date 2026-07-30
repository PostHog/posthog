import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import type { DataWarehouseSavedQuery, DataWarehouseTable, PropertyDefinition } from '~/types'
import { PropertyDefinitionType } from '~/types'

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
    CustomPropertyOptionApi,
    CustomPropertyReferenceApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { NEW_OPTION_ID_PREFIX, isNumericDisplayType, optionLabelError } from './customPropertyTypes'

export type CustomPropertySourceMode = 'manual' | 'data_warehouse' | 'workflow'
export type CustomPropertyTargetType = 'account' | 'person'

// One warehouse-column → person-property pair in the person-target editor. Serialized to the
// backend's `column_property_map` object ({column: property}) on save.
export interface ColumnPropertyMapping {
    column: string
    property: string
}

export interface CustomPropertyFormValues {
    name: string
    description: string
    displayType: CustomPropertyDisplayTypeEnumApi
    isBigNumber: boolean
    options: CustomPropertyOptionApi[]
    // 'account' feeds an account (group) property from a saved query; 'person' upserts warehouse
    // columns onto person properties (usable in flags/cohorts/insights) from a raw synced table.
    targetType: CustomPropertyTargetType
    sourceMode: CustomPropertySourceMode
    savedQuery: string | null
    sourceColumn: string | null
    keyColumn: string | null
    // Person target: the warehouse table (its schema id backs the source) + the column mappings.
    warehouseTable: string | null
    columnMappings: ColumnPropertyMapping[]
    isEnabled: boolean
}

const DEFAULT_FORM_VALUES: CustomPropertyFormValues = {
    name: '',
    description: '',
    displayType: 'text',
    isBigNumber: false,
    options: [],
    targetType: 'account',
    sourceMode: 'manual',
    savedQuery: null,
    sourceColumn: null,
    keyColumn: null,
    warehouseTable: null,
    columnMappings: [{ column: '', property: '' }],
    isEnabled: true,
}

const serializeDefinition = ({
    name,
    description,
    displayType,
    isBigNumber,
    options,
    targetType,
}: CustomPropertyFormValues): {
    name: string
    description: string | null
    display_type: CustomPropertyDisplayTypeEnumApi
    target_type: CustomPropertyTargetType
    is_big_number: boolean
    options?: CustomPropertyOptionApi[]
} => ({
    name: name.trim(),
    description: description?.trim() || null,
    display_type: displayType,
    // Create-only on the backend; a definition's target doesn't change after creation.
    target_type: targetType,
    // The switch is hidden for non-numeric types, so never send a stale flag for them.
    is_big_number: isNumericDisplayType(displayType) ? isBigNumber : false,
    // Options only apply to select; the backend clears them for other types.
    ...(displayType === 'select'
        ? {
              options: options.map(({ id, label, color }) => ({
                  ...(id && !id.startsWith(NEW_OPTION_ID_PREFIX) ? { id } : {}),
                  label: label.trim(),
                  color,
              })),
          }
        : {}),
})

// Identity-critical person properties a warehouse source shouldn't silently overwrite. `$`-prefixed
// props are also warned on (see columnMappingWarnings). Warn-only — the user can still proceed.
const RESERVED_PERSON_PROPERTY_NAMES = new Set(['email', 'name', 'username'])

// The backend stores column_property_map as a JSON object; the form edits it as an ordered list.
const parseColumnPropertyMap = (value: unknown): ColumnPropertyMapping[] => {
    if (!value || typeof value !== 'object') {
        return [{ column: '', property: '' }]
    }
    const entries = Object.entries(value as Record<string, unknown>).map(([column, property]) => ({
        column,
        property: String(property),
    }))
    return entries.length ? entries : [{ column: '', property: '' }]
}

const handleNameConflict = (error: unknown, setManualErrors: (errors: { name: string }) => void): boolean => {
    if ((error as { status?: number })?.status !== 409) {
        return false
    }
    setManualErrors({ name: 'A custom property with this name already exists.' })
    return true
}

class MissingNameError extends Error {}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface customPropertyDefinitionsLogicValues {
    currentProjectId: number | null // projectLogic
    columnMappingWarnings: (string | null)[]
    customPropertyForm: CustomPropertyFormValues
    customPropertyFormAllErrors: Record<string, any>
    customPropertyFormChanged: boolean
    customPropertyFormErrors: DeepPartialMap<CustomPropertyFormValues, ValidationErrorType>
    customPropertyFormHasErrors: boolean
    customPropertyFormManualErrors: Record<string, any>
    customPropertyFormTouched: boolean
    customPropertyFormTouches: Record<string, boolean>
    customPropertyFormValidationErrors: DeepPartialMap<CustomPropertyFormValues, ValidationErrorType>
    definitions: CustomPropertyDefinitionApi[]
    definitionsLoading: boolean
    editingDefinition: CustomPropertyDefinitionApi | null
    editingReferences: readonly CustomPropertyReferenceApi[]
    isCustomPropertyFormSubmitting: boolean
    isCustomPropertyFormValid: boolean
    materializedViews: DataWarehouseSavedQuery[]
    modalVisible: boolean
    newWorkflowUrl: string | null
    newWorkflowUrlLoading: boolean
    personPropertyDefinitions: PropertyDefinition[]
    personPropertyDefinitionsLoading: boolean
    savedQueries: DataWarehouseSavedQuery[]
    savedQueriesLoading: boolean
    selectedSourceColumns: string[]
    selectedWarehouseSchemaId: string | null
    serializedColumnPropertyMap: Record<string, string>
    showCustomPropertyFormErrors: boolean
    warehouseTables: DataWarehouseTable[]
    warehouseTablesLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface customPropertyDefinitionsLogicActions {
    closeModal: () => {
        value: true
    }
    createWorkflowForProperty: () => any
    createWorkflowForPropertyFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    createWorkflowForPropertySuccess: (
        newWorkflowUrl: string,
        payload?: any
    ) => {
        newWorkflowUrl: string
        payload?: any
    }
    deleteDefinition: ({ id }: { id: string }) => {
        id: string
    }
    deleteDefinitionFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    deleteDefinitionSuccess: (
        definitions: CustomPropertyDefinitionApi[],
        payload?: {
            id: string
        }
    ) => {
        definitions: CustomPropertyDefinitionApi[]
        payload?: {
            id: string
        }
    }
    loadDefinitions: () => any
    loadDefinitionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadDefinitionsSuccess: (
        definitions: CustomPropertyDefinitionApi[],
        payload?: any
    ) => {
        definitions: CustomPropertyDefinitionApi[]
        payload?: any
    }
    loadPersonPropertyDefinitions: () => any
    loadPersonPropertyDefinitionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPersonPropertyDefinitionsSuccess: (
        personPropertyDefinitions: PropertyDefinition[],
        payload?: any
    ) => {
        personPropertyDefinitions: PropertyDefinition[]
        payload?: any
    }
    loadSavedQueries: () => any
    loadSavedQueriesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSavedQueriesSuccess: (
        savedQueries: DataWarehouseSavedQuery[],
        payload?: any
    ) => {
        savedQueries: DataWarehouseSavedQuery[]
        payload?: any
    }
    loadWarehouseTables: () => any
    loadWarehouseTablesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadWarehouseTablesSuccess: (
        warehouseTables: DataWarehouseTable[],
        payload?: any
    ) => {
        warehouseTables: DataWarehouseTable[]
        payload?: any
    }
    openCreateModal: () => {
        value: true
    }
    openEditModal: (definition: CustomPropertyDefinitionApi) => {
        definition: CustomPropertyDefinitionApi
    }
    resetCustomPropertyForm: (values?: CustomPropertyFormValues) => {
        values?: CustomPropertyFormValues
    }
    setCustomPropertyFormManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setCustomPropertyFormValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setCustomPropertyFormValues: (values: DeepPartial<CustomPropertyFormValues>) => {
        values: DeepPartial<CustomPropertyFormValues>
    }
    setEditingDefinition: (definition: CustomPropertyDefinitionApi) => {
        definition: CustomPropertyDefinitionApi
    }
    submitCustomPropertyForm: () => {
        value: boolean
    }
    submitCustomPropertyFormFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitCustomPropertyFormRequest: (customPropertyForm: CustomPropertyFormValues) => {
        customPropertyForm: CustomPropertyFormValues
    }
    submitCustomPropertyFormSuccess: (customPropertyForm: CustomPropertyFormValues) => {
        customPropertyForm: CustomPropertyFormValues
    }
    touchCustomPropertyFormField: (key: string) => {
        key: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface customPropertyDefinitionsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        materializedViews: (savedQueries: DataWarehouseSavedQuery[]) => DataWarehouseSavedQuery[]
        selectedSourceColumns: (
            savedQueries: DataWarehouseSavedQuery[],
            customPropertyForm: CustomPropertyFormValues
        ) => string[]
        selectedWarehouseSchemaId: (
            warehouseTables: DataWarehouseTable[],
            customPropertyForm: CustomPropertyFormValues
        ) => string | null
        serializedColumnPropertyMap: (customPropertyForm: CustomPropertyFormValues) => Record<string, string>
        columnMappingWarnings: (
            customPropertyForm: CustomPropertyFormValues,
            personPropertyDefinitions: PropertyDefinition[]
        ) => (string | null)[]
        editingReferences: (
            definitions: CustomPropertyDefinitionApi[],
            editingDefinition: CustomPropertyDefinitionApi | null
        ) => readonly CustomPropertyReferenceApi[]
    }
}

export type customPropertyDefinitionsLogicType = MakeLogicType<
    customPropertyDefinitionsLogicValues,
    customPropertyDefinitionsLogicActions,
    Record<string, any>,
    customPropertyDefinitionsLogicMeta
>

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
        warehouseTables: [
            [] as DataWarehouseTable[],
            {
                loadWarehouseTables: async (): Promise<DataWarehouseTable[]> => {
                    const response = await api.dataWarehouseTables.list()
                    // Only synced tables carry an external_schema, which is what a person source binds to.
                    return response.results.filter((table) => !!table.external_schema)
                },
            },
        ],
        personPropertyDefinitions: [
            [] as PropertyDefinition[],
            {
                loadPersonPropertyDefinitions: async (): Promise<PropertyDefinition[]> => {
                    const response = await api.propertyDefinitions.list({
                        type: PropertyDefinitionType.Person,
                        limit: 1000,
                    })
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
                        // Announce the side effect: the property now exists even if the modal is cancelled.
                        lemonToast.success('Custom property created')
                    }
                    return urls.workflowNew()
                },
            },
        ],
    })),
    forms(({ actions, values }) => ({
        customPropertyForm: {
            defaults: DEFAULT_FORM_VALUES,
            errors: ({
                name,
                displayType,
                options,
                targetType,
                sourceMode,
                savedQuery,
                sourceColumn,
                keyColumn,
                warehouseTable,
            }: CustomPropertyFormValues) => {
                const isPerson = targetType === 'person'
                const isAccountWarehouse = !isPerson && sourceMode === 'data_warehouse'
                // The table + column map are create-only, so only require them when creating a new
                // person source — an existing source keeps only key_column and enabled editable.
                const isNewPersonSource = isPerson && !values.editingDefinition?.source
                return {
                    name: !name?.trim() ? 'Name is required' : undefined,
                    options:
                        !isPerson && displayType === 'select'
                            ? options.map((_, index) => ({ label: optionLabelError(options, index) }))
                            : undefined,
                    savedQuery: isAccountWarehouse && !savedQuery ? 'Select a view' : undefined,
                    sourceColumn: isAccountWarehouse && !sourceColumn ? 'Select the value column' : undefined,
                    keyColumn:
                        (isAccountWarehouse || isPerson) && !keyColumn?.trim() ? 'Enter the key column' : undefined,
                    warehouseTable: isNewPersonSource && !warehouseTable ? 'Select a warehouse table' : undefined,
                }
            },
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
                    const { targetType, sourceMode, savedQuery, sourceColumn, keyColumn, isEnabled } = formValues
                    const existingSource = editing?.source ?? null
                    if (targetType === 'person') {
                        const schemaId = values.selectedWarehouseSchemaId
                        if (existingSource) {
                            // The binding + column map are create-only on the backend; only key_column
                            // and is_enabled are mutable on a person source.
                            await customPropertySourcesPartialUpdate(projectId, existingSource.id, {
                                key_column: keyColumn ?? '',
                                is_enabled: isEnabled,
                            })
                        } else if (!schemaId) {
                            // Form validation passed but the table's schema no longer resolves — it was
                            // deleted or unsynced between load and save. Surface it instead of silently
                            // creating the definition without its source.
                            throw new Error('The selected warehouse table is no longer available')
                        } else if (!keyColumn?.trim()) {
                            throw new Error('Enter the distinct ID column')
                        } else {
                            await customPropertySourcesCreate(projectId, {
                                definition: definition.id,
                                external_data_schema: schemaId,
                                column_property_map: values.serializedColumnPropertyMap,
                                key_column: keyColumn.trim(),
                                is_enabled: isEnabled,
                            })
                        }
                    } else if (sourceMode === 'data_warehouse' && savedQuery && sourceColumn && keyColumn) {
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
        // The chosen warehouse table's schema id — what a person source actually binds to.
        selectedWarehouseSchemaId: [
            (s) => [s.warehouseTables, s.customPropertyForm],
            (warehouseTables: DataWarehouseTable[], form: CustomPropertyFormValues): string | null =>
                warehouseTables.find((table) => table.id === form.warehouseTable)?.external_schema?.id ?? null,
        ],
        // The person-target column mappings as the backend's `column_property_map` object.
        serializedColumnPropertyMap: [
            (s) => [s.customPropertyForm],
            (form: CustomPropertyFormValues): Record<string, string> =>
                Object.fromEntries(
                    form.columnMappings
                        .filter((mapping) => mapping.column.trim() && mapping.property.trim())
                        .map((mapping) => [mapping.column.trim(), mapping.property.trim()])
                ),
        ],
        // Warn-only collision check per mapping: a chosen person-property name that is `$`-prefixed,
        // an identity property, or already defined on persons could overwrite existing values.
        columnMappingWarnings: [
            (s) => [s.customPropertyForm, s.personPropertyDefinitions],
            (form: CustomPropertyFormValues, personPropertyDefinitions: PropertyDefinition[]): (string | null)[] => {
                const existing = new Set(personPropertyDefinitions.map((definition) => definition.name))
                return form.columnMappings.map((mapping) => {
                    const name = mapping.property.trim()
                    if (!name) {
                        return null
                    }
                    if (name.startsWith('$') || RESERVED_PERSON_PROPERTY_NAMES.has(name)) {
                        return `"${name}" is an identity property — writing to it may overwrite SDK-set values.`
                    }
                    if (existing.has(name)) {
                        return `A person property "${name}" already exists — this source will overwrite it.`
                    }
                    return null
                })
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
    listeners(({ actions }) => ({
        openCreateModal: () => {
            actions.resetCustomPropertyForm()
            actions.loadSavedQueries()
            actions.loadWarehouseTables()
            actions.loadPersonPropertyDefinitions()
        },
        openEditModal: ({ definition }) => {
            actions.loadSavedQueries()
            actions.loadWarehouseTables()
            actions.loadPersonPropertyDefinitions()
            const isPerson = definition.target_type === 'person'
            actions.setCustomPropertyFormValues({
                name: definition.name,
                description: definition.description ?? '',
                displayType: definition.display_type,
                isBigNumber: definition.is_big_number ?? false,
                options: definition.options ?? [],
                targetType: isPerson ? 'person' : 'account',
                sourceMode: definition.source
                    ? 'data_warehouse'
                    : definition.references?.length
                      ? 'workflow'
                      : 'manual',
                savedQuery: definition.source?.saved_query ?? null,
                sourceColumn: definition.source?.source_column ?? null,
                keyColumn: definition.source?.key_column ?? null,
                // The warehouse-table binding is create-only, so on edit we surface the existing map
                // (read-only in the modal) rather than resolving the table back for the picker.
                warehouseTable: null,
                columnMappings: isPerson
                    ? parseColumnPropertyMap(definition.source?.column_property_map)
                    : [{ column: '', property: '' }],
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
        deleteDefinitionFailure: ({ errorObject }) => {
            // An already-deleted definition (double-click, stale table, concurrent delete) 404s.
            // The delete effectively succeeded, so refresh the table without capturing an exception.
            if ((errorObject as { status?: number })?.status === 404) {
                actions.loadDefinitions()
                lemonToast.success('Custom property deleted')
                return
            }
            posthog.captureException(errorObject, { scope: 'customPropertyDefinitionsLogic.delete' })
            lemonToast.error('Failed to delete custom property')
        },
        loadDefinitionsFailure: ({ error }) => {
            posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.load' })
            lemonToast.error('Failed to load custom properties')
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
            // A name conflict is expected validation feedback, not an exception worth capturing.
            if (handleNameConflict(errorObject, actions.setCustomPropertyFormManualErrors)) {
                return
            }
            posthog.captureException(errorObject, { scope: 'customPropertyDefinitionsLogic.createWorkflow' })
            lemonToast.error('Failed to create workflow')
        },
        loadSavedQueriesFailure: ({ error }) => {
            posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.loadSavedQueries' })
            lemonToast.error('Failed to load data warehouse views')
        },
        loadWarehouseTablesFailure: ({ error }) => {
            posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.loadWarehouseTables' })
            lemonToast.error('Failed to load data warehouse tables')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDefinitions()
    }),
])
