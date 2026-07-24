import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import type { DataWarehouseSavedQuery, DataWarehouseTable, PropertyDefinition } from '~/types'
import { PropertyDefinitionType } from '~/types'

import {
    customPropertyDefinitionsCreate,
    customPropertyDefinitionsDestroy,
    customPropertyDefinitionsList,
    customPropertyDefinitionsPartialUpdate,
    customPropertySourcesBackfill,
    customPropertySourcesCreate,
    customPropertySourcesDestroy,
    customPropertySourcesPartialUpdate,
    customPropertySourcesRunsList,
    customPropertySourcesSync,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    CustomPropertyDefinitionApi,
    CustomPropertyDisplayTypeEnumApi,
    CustomPropertyOptionApi,
    CustomPropertyReferenceApi,
    CustomPropertySyncRunApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { NEW_OPTION_ID_PREFIX, isNumericDisplayType, optionLabelError } from './customPropertyTypes'

export type CustomPropertySourceMode = 'manual' | 'data_warehouse' | 'workflow'
export type CustomPropertyTargetType = 'account' | 'person' | 'group'

// After triggering a sync/backfill, poll until the source's run settles so the UI reflects
// completion without a manual refresh. Bounded so a stuck run can't poll forever.
const RUNS_POLL_INTERVAL_MS = 3000
const RUNS_POLL_MAX_ATTEMPTS = 20

// One warehouse-column → person-property pair in the person-target editor. Serialized to the
// backend's `column_property_map` object ({column: property}) on save; the optional per-mapping
// description is serialized to `column_descriptions` ({column: description}).
export interface ColumnPropertyMapping {
    column: string
    property: string
    description: string
}

// A warehouse table column as offered in the pickers: its name, HogQL type (shown as a tag), and
// canonical description (seeded into a mapping's description when the column is picked).
export interface WarehouseColumn {
    name: string
    type: string
    description: string | null
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
    // Group target only: which group type (0-4) the property attaches to.
    groupTypeIndex: number | null
    sourceMode: CustomPropertySourceMode
    savedQuery: string | null
    sourceColumn: string | null
    keyColumn: string | null
    // Person/group target: the warehouse table (its schema id backs the source) + the column mappings.
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
    groupTypeIndex: null,
    sourceMode: 'manual',
    savedQuery: null,
    sourceColumn: null,
    keyColumn: null,
    warehouseTable: null,
    columnMappings: [{ column: '', property: '', description: '' }],
    isEnabled: true,
}

const serializeDefinition = ({
    name,
    description,
    displayType,
    isBigNumber,
    options,
    targetType,
    groupTypeIndex,
}: CustomPropertyFormValues): {
    name: string
    description: string | null
    display_type: CustomPropertyDisplayTypeEnumApi
    target_type: CustomPropertyTargetType
    group_type_index?: number | null
    is_big_number: boolean
    options?: CustomPropertyOptionApi[]
} => {
    // display_type/is_big_number/options only drive how an account property renders — person and
    // group properties are written as raw $set / $group_set values, so those are hidden and defaulted.
    const isProfile = targetType === 'person' || targetType === 'group'
    return {
        name: name.trim(),
        description: description?.trim() || null,
        display_type: isProfile ? 'text' : displayType,
        // Create-only on the backend; a definition's target doesn't change after creation.
        target_type: targetType,
        // The group type is create-only too; sent only for group targets, omitted otherwise.
        ...(targetType === 'group' ? { group_type_index: groupTypeIndex } : {}),
        // The switch is hidden for non-numeric types, so never send a stale flag for them.
        is_big_number: !isProfile && isNumericDisplayType(displayType) ? isBigNumber : false,
        // Options only apply to select; the backend clears them for other types.
        ...(!isProfile && displayType === 'select'
            ? {
                  options: options.map(({ id, label, color }) => ({
                      ...(id && !id.startsWith(NEW_OPTION_ID_PREFIX) ? { id } : {}),
                      label: label.trim(),
                      color,
                  })),
              }
            : {}),
    }
}

// Identity-critical person properties a warehouse source shouldn't silently overwrite. `$`-prefixed
// props are also warned on (see columnMappingWarnings). Warn-only — the user can still proceed.
const RESERVED_PERSON_PROPERTY_NAMES = new Set(['email', 'name', 'username'])

// The backend stores column_property_map as a JSON object; the form edits it as an ordered list.
// Descriptions are stored in a parallel {column: description} object and folded back in per column.
const parseColumnPropertyMap = (value: unknown, descriptions: unknown): ColumnPropertyMapping[] => {
    const descriptionsByColumn =
        descriptions && typeof descriptions === 'object' ? (descriptions as Record<string, unknown>) : {}
    if (!value || typeof value !== 'object') {
        return [{ column: '', property: '', description: '' }]
    }
    const entries = Object.entries(value as Record<string, unknown>).map(([column, property]) => ({
        column,
        property: String(property),
        description: descriptionsByColumn[column] != null ? String(descriptionsByColumn[column]) : '',
    }))
    return entries.length ? entries : [{ column: '', property: '', description: '' }]
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
    runsBySourceId: Record<string, CustomPropertySyncRunApi[]>
    runsLoadingBySourceId: Record<string, boolean>
    savedQueries: DataWarehouseSavedQuery[]
    savedQueriesLoading: boolean
    selectedSourceColumns: string[]
    selectedTableColumns: WarehouseColumn[]
    selectedTableColumnsLoading: boolean
    selectedWarehouseSchemaId: string | null
    serializedColumnDescriptions: Record<string, string>
    serializedColumnPropertyMap: Record<string, string>
    showCustomPropertyFormErrors: boolean
    targetTypeLocked: boolean
    triggeringSourceIds: string[]
    warehouseTables: DataWarehouseTable[]
    warehouseTablesLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface customPropertyDefinitionsLogicActions {
    addTriggeringSource: ({ sourceId }: { sourceId: string }) => {
        sourceId: string
    }
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
    loadRuns: ({ sourceId }: { sourceId: string }) => {
        sourceId: string
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
    loadSelectedTableColumns: ({ tableId }: { tableId: string | null }) => {
        tableId: string | null
    }
    loadSelectedTableColumnsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSelectedTableColumnsSuccess: (
        selectedTableColumns: WarehouseColumn[],
        payload?: {
            tableId: string | null
        }
    ) => {
        selectedTableColumns: WarehouseColumn[]
        payload?: {
            tableId: string | null
        }
    }
    loadWarehouseTables: ({ search }?: { search?: string }) => {
        search?: string
    }
    loadWarehouseTablesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadWarehouseTablesSuccess: (
        warehouseTables: DataWarehouseTable[],
        payload?: {
            search?: string
        }
    ) => {
        warehouseTables: DataWarehouseTable[]
        payload?: {
            search?: string
        }
    }
    openCreateModal: (
        targetType?: CustomPropertyTargetType,
        lockTargetType?: boolean
    ) => {
        lockTargetType: boolean
        targetType: CustomPropertyTargetType | undefined
    }
    openEditModal: (definition: CustomPropertyDefinitionApi) => {
        definition: CustomPropertyDefinitionApi
    }
    pollRunsStatus: ({ sourceId }: { sourceId: string }) => {
        sourceId: string
    }
    removeTriggeringSource: ({ sourceId }: { sourceId: string }) => {
        sourceId: string
    }
    resetCustomPropertyForm: (values?: CustomPropertyFormValues) => {
        values?: CustomPropertyFormValues
    }
    runsLoadFailed: ({ sourceId }: { sourceId: string }) => {
        sourceId: string
    }
    runsLoaded: ({ sourceId, runs }: { runs: CustomPropertySyncRunApi[]; sourceId: string }) => {
        runs: CustomPropertySyncRunApi[]
        sourceId: string
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
    triggerBackfill: ({ sourceId }: { sourceId: string }) => {
        sourceId: string
    }
    triggerSync: ({ sourceId }: { sourceId: string }) => {
        sourceId: string
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
        serializedColumnDescriptions: (customPropertyForm: CustomPropertyFormValues) => Record<string, string>
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
        // An optional target pre-selects Account/Person/Group (the person- and group-properties
        // settings entries open straight into their target); omitted, it falls back to the account
        // default. lockTargetType hides the "Attach to" switch when the target is implied by where
        // the modal was opened (the person/group settings pages).
        openCreateModal: (targetType?: CustomPropertyTargetType, lockTargetType: boolean = false) => ({
            targetType,
            lockTargetType,
        }),
        openEditModal: (definition: CustomPropertyDefinitionApi) => ({ definition }),
        closeModal: true,
        setEditingDefinition: (definition: CustomPropertyDefinitionApi) => ({ definition }),
        // Person sources only. triggerSync re-runs the underlying warehouse sync; triggerBackfill
        // starts a full-table backfill. add/removeTriggeringSource drive the per-row double-submit
        // guard, keyed by source so triggering one row never re-enables another's in-flight button.
        triggerSync: ({ sourceId }: { sourceId: string }) => ({ sourceId }),
        triggerBackfill: ({ sourceId }: { sourceId: string }) => ({ sourceId }),
        addTriggeringSource: ({ sourceId }: { sourceId: string }) => ({ sourceId }),
        removeTriggeringSource: ({ sourceId }: { sourceId: string }) => ({ sourceId }),
        // Run history per source (lazy on row-expand), driven by explicit actions so loading state is
        // tracked per source rather than one shared loader boolean.
        loadRuns: ({ sourceId }: { sourceId: string }) => ({ sourceId }),
        runsLoaded: ({ sourceId, runs }: { sourceId: string; runs: CustomPropertySyncRunApi[] }) => ({
            sourceId,
            runs,
        }),
        runsLoadFailed: ({ sourceId }: { sourceId: string }) => ({ sourceId }),
        // Poll definitions/runs after a trigger until the source's run settles, so the buttons and
        // status stop reflecting a stale 'running' state without a manual page refresh.
        pollRunsStatus: ({ sourceId }: { sourceId: string }) => ({ sourceId }),
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
        // Whether the "Attach to" switch is hidden because the target is fixed by where the modal was
        // opened (the person/group settings pages). Editing never shows the switch as a control anyway.
        targetTypeLocked: [
            false,
            {
                openCreateModal: (_, { lockTargetType }) => lockTargetType,
                openEditModal: () => false,
                closeModal: () => false,
            },
        ],
        // The sources whose sync/backfill trigger is in flight, for the per-row loading/disabled guard.
        // Keyed per source (not a single scalar) so a second row's trigger can't unblock the first's
        // still-in-flight button.
        triggeringSourceIds: [
            [] as string[],
            {
                addTriggeringSource: (state, { sourceId }) => (state.includes(sourceId) ? state : [...state, sourceId]),
                removeTriggeringSource: (state, { sourceId }) => state.filter((id) => id !== sourceId),
            },
        ],
        // Sync/backfill run history per person source, loaded lazily when a row is expanded.
        runsBySourceId: [
            {} as Record<string, CustomPropertySyncRunApi[]>,
            {
                runsLoaded: (state, { sourceId, runs }) => ({ ...state, [sourceId]: runs }),
            },
        ],
        // Per-source loading flag so expanding one row's history doesn't spin every expanded row.
        runsLoadingBySourceId: [
            {} as Record<string, boolean>,
            {
                loadRuns: (state, { sourceId }) => ({ ...state, [sourceId]: true }),
                runsLoaded: (state, { sourceId }) => ({ ...state, [sourceId]: false }),
                runsLoadFailed: (state, { sourceId }) => ({ ...state, [sourceId]: false }),
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
                loadWarehouseTables: async (
                    { search }: { search?: string } = {},
                    breakpoint
                ): Promise<DataWarehouseTable[]> => {
                    // Debounce keystrokes from the picker's server-side search so typing doesn't fire a
                    // request per character.
                    await breakpoint(300)
                    // Skip column serialization (expensive per-table HogQL work) — the picker only needs
                    // names, and columns load per-table on selection. Search runs on the backend, and we
                    // follow pagination so more than one page of synced tables is reachable (bounded, so a
                    // broad, unsearched catalog can't pull forever).
                    const PAGE_SIZE = 100
                    const MAX_PAGES = 20
                    const collected: DataWarehouseTable[] = []
                    for (let offset = 0, page = 0; page < MAX_PAGES; page += 1, offset += PAGE_SIZE) {
                        const response = await api.dataWarehouseTables.list({
                            include_columns: false,
                            limit: PAGE_SIZE,
                            offset,
                            ...(search ? { search } : {}),
                        })
                        breakpoint()
                        collected.push(...response.results)
                        if (!response.next || response.results.length < PAGE_SIZE) {
                            break
                        }
                    }
                    // Only synced tables carry an external_schema, which is what a person source binds to.
                    const synced = collected.filter((table) => !!table.external_schema)
                    // Keep the currently-selected table in the list even if the active search filters it
                    // out, so the picker can still render its label rather than a bare id.
                    const selectedId = values.customPropertyForm.warehouseTable
                    if (selectedId && !synced.some((table) => table.id === selectedId)) {
                        const selected = values.warehouseTables.find((table) => table.id === selectedId)
                        if (selected) {
                            return [selected, ...synced]
                        }
                    }
                    return synced
                },
            },
        ],
        selectedTableColumns: [
            [] as WarehouseColumn[],
            {
                loadSelectedTableColumns: async ({
                    tableId,
                }: {
                    tableId: string | null
                }): Promise<WarehouseColumn[]> => {
                    if (!tableId) {
                        return []
                    }
                    const table = await api.dataWarehouseTables.get(tableId)
                    const columns: WarehouseColumn[] = (table.columns ?? []).map((column) => ({
                        name: column.name,
                        type: String(column.type),
                        description: null,
                    }))
                    // Seed each column's canonical description from the warehouse catalog. Best-effort:
                    // descriptions are often unset for warehouse columns, and the catalog query mustn't
                    // block picking columns, so any failure leaves descriptions null.
                    try {
                        const tableName = table.hogql_name || table.name
                        const response = (await api.query({
                            kind: NodeKind.HogQLQuery,
                            query: hogql`
                                select column_name, description
                                from information_schema.columns
                                where table_name = ${tableName}
                            `,
                        })) as HogQLQueryResponse
                        const descriptionByColumn = new Map<string, string>()
                        for (const row of (response.results ?? []) as unknown[][]) {
                            const name = row[0] as string | null
                            const description = row[1] as string | null
                            if (name && description) {
                                descriptionByColumn.set(name, description)
                            }
                        }
                        return columns.map((column) => ({
                            ...column,
                            description: descriptionByColumn.get(column.name) ?? null,
                        }))
                    } catch {
                        return columns
                    }
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
                groupTypeIndex,
                sourceMode,
                savedQuery,
                sourceColumn,
                keyColumn,
                warehouseTable,
            }: CustomPropertyFormValues) => {
                // Person and group both feed from a warehouse table; account can also via a view.
                const isProfile = targetType === 'person' || targetType === 'group'
                const isAccountWarehouse = !isProfile && sourceMode === 'data_warehouse'
                // The table + column map are create-only, so only require them when creating a new
                // profile source — an existing source keeps only key_column and enabled editable.
                const isNewProfileSource = isProfile && !values.editingDefinition?.source
                return {
                    name: !name?.trim() ? 'Name is required' : undefined,
                    groupTypeIndex:
                        targetType === 'group' && groupTypeIndex == null ? 'Select a group type' : undefined,
                    options:
                        !isProfile && displayType === 'select'
                            ? options.map((_, index) => ({ label: optionLabelError(options, index) }))
                            : undefined,
                    savedQuery: isAccountWarehouse && !savedQuery ? 'Select a view' : undefined,
                    sourceColumn: isAccountWarehouse && !sourceColumn ? 'Select the value column' : undefined,
                    keyColumn:
                        (isAccountWarehouse || isProfile) && !keyColumn?.trim() ? 'Enter the key column' : undefined,
                    warehouseTable: isNewProfileSource && !warehouseTable ? 'Select a warehouse table' : undefined,
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
                    // Person and group sources share the same warehouse binding (schema + column map).
                    if (targetType === 'person' || targetType === 'group') {
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
                                column_descriptions: values.serializedColumnDescriptions,
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
        // The per-mapping descriptions as the backend's `column_descriptions` object ({column:
        // description}), only for complete mappings that carry a non-empty description.
        serializedColumnDescriptions: [
            (s) => [s.customPropertyForm],
            (form: CustomPropertyFormValues): Record<string, string> =>
                Object.fromEntries(
                    form.columnMappings
                        .filter(
                            (mapping) => mapping.column.trim() && mapping.property.trim() && mapping.description.trim()
                        )
                        .map((mapping) => [mapping.column.trim(), mapping.description.trim()])
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
    listeners(({ actions, values, cache }) => ({
        openCreateModal: ({ targetType }) => {
            actions.resetCustomPropertyForm()
            if (targetType) {
                actions.setCustomPropertyFormValue('targetType', targetType)
            }
            actions.loadSavedQueries()
            actions.loadWarehouseTables()
            actions.loadPersonPropertyDefinitions()
            // No table picked yet — clear any columns left over from a previous open.
            actions.loadSelectedTableColumnsSuccess([])
        },
        openEditModal: ({ definition }) => {
            actions.loadSavedQueries()
            actions.loadWarehouseTables()
            actions.loadPersonPropertyDefinitions()
            const targetType: CustomPropertyTargetType =
                definition.target_type === 'person' || definition.target_type === 'group'
                    ? definition.target_type
                    : 'account'
            const isProfile = targetType === 'person' || targetType === 'group'
            actions.setCustomPropertyFormValues({
                name: definition.name,
                description: definition.description ?? '',
                displayType: definition.display_type,
                isBigNumber: definition.is_big_number ?? false,
                options: definition.options ?? [],
                targetType,
                groupTypeIndex: definition.group_type_index ?? null,
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
                columnMappings: isProfile
                    ? parseColumnPropertyMap(
                          definition.source?.column_property_map,
                          definition.source?.column_descriptions
                      )
                    : [{ column: '', property: '', description: '' }],
                isEnabled: definition.source?.is_enabled ?? true,
            })
        },
        loadWarehouseTablesSuccess: () => {
            // On edit the table binding is create-only and hidden, but the distinct-ID column stays
            // editable — so resolve the bound table from the source's schema and load its columns to
            // drive that picker. Resolving here (not in openEditModal) waits for the table list to load.
            const source = values.editingDefinition?.source
            if (source?.external_data_schema) {
                const table = values.warehouseTables.find(
                    (candidate) => candidate.external_schema?.id === source.external_data_schema
                )
                if (table) {
                    actions.loadSelectedTableColumns({ tableId: table.id })
                }
            }
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
        triggerSync: async ({ sourceId }) => {
            actions.addTriggeringSource({ sourceId })
            try {
                await customPropertySourcesSync(String(values.currentProjectId), sourceId)
                lemonToast.success('Sync triggered — it may take a few minutes to run')
                actions.loadDefinitions()
                actions.pollRunsStatus({ sourceId })
            } catch (error) {
                posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.triggerSync' })
                lemonToast.error('Could not trigger a sync for this property')
            } finally {
                actions.removeTriggeringSource({ sourceId })
            }
        },
        triggerBackfill: async ({ sourceId }) => {
            actions.addTriggeringSource({ sourceId })
            try {
                const response = await customPropertySourcesBackfill(String(values.currentProjectId), sourceId)
                const alreadyRunning = (response as { already_running?: boolean } | undefined)?.already_running
                lemonToast.success(
                    alreadyRunning
                        ? 'A backfill is already running for this table'
                        : 'Backfill started — it may take a few minutes to run'
                )
                actions.loadRuns({ sourceId })
                actions.loadDefinitions()
                actions.pollRunsStatus({ sourceId })
            } catch (error) {
                posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.triggerBackfill' })
                lemonToast.error('Could not start a backfill for this property')
            } finally {
                actions.removeTriggeringSource({ sourceId })
            }
        },
        loadRuns: async ({ sourceId }) => {
            try {
                const response = await customPropertySourcesRunsList(String(values.currentProjectId), sourceId)
                actions.runsLoaded({ sourceId, runs: response.results })
            } catch (error) {
                posthog.captureException(error, { scope: 'customPropertyDefinitionsLogic.loadRuns' })
                actions.runsLoadFailed({ sourceId })
                lemonToast.error('Failed to load run history')
            }
        },
        pollRunsStatus: ({ sourceId }) => {
            cache.pollSourceIds = cache.pollSourceIds ?? new Set<string>()
            cache.pollAttempts = cache.pollAttempts ?? {}
            cache.pollSourceIds.add(sourceId)
            cache.pollAttempts[sourceId] = 0
            cache.disposables.add(() => {
                const timeoutId = setTimeout(() => actions.loadDefinitions(), RUNS_POLL_INTERVAL_MS)
                return () => clearTimeout(timeoutId)
            }, 'runsPoll')
        },
        loadDefinitionsSuccess: () => {
            // Reschedule the trigger poll until each polled source's run settles (or attempts run out),
            // so the buttons/status reflect completion without a manual refresh (see pollRunsStatus).
            const pollSourceIds: Set<string> | undefined = cache.pollSourceIds
            if (!pollSourceIds || pollSourceIds.size === 0) {
                return
            }
            // Build the next round rather than mutating the set while iterating it.
            const stillPolling = new Set<string>()
            pollSourceIds.forEach((sourceId) => {
                const definition = values.definitions.find((d) => d.source?.id === sourceId)
                const stillRunning = definition?.source?.latest_run?.status === 'running'
                const attempts = (cache.pollAttempts[sourceId] ?? 0) + 1
                cache.pollAttempts[sourceId] = attempts
                actions.loadRuns({ sourceId })
                if (stillRunning && attempts < RUNS_POLL_MAX_ATTEMPTS) {
                    stillPolling.add(sourceId)
                }
            })
            cache.pollSourceIds = stillPolling
            if (stillPolling.size === 0) {
                cache.disposables.dispose('runsPoll')
                return
            }
            cache.disposables.add(() => {
                const timeoutId = setTimeout(() => actions.loadDefinitions(), RUNS_POLL_INTERVAL_MS)
                return () => clearTimeout(timeoutId)
            }, 'runsPoll')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDefinitions()
    }),
])
