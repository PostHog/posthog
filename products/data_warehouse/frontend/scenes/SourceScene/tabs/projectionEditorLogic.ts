import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { objectsEqual } from 'lib/utils'

import { ExternalDataSource } from '~/types'

import type { projectionEditorLogicType } from './projectionEditorLogicType'
import {
    getRawProjectionSchemaMetadata,
    DirectPostgresProjectionCustomField,
    DirectPostgresProjectionForeignKey,
    DirectPostgresProjectionRevision,
    DirectPostgresProjectionTableConfig,
    ExternalDataSourceSchemaWithProjectionMetadata,
    ExternalDataSourceWithProjectionMetadata,
} from './projectionTypes'
import { sourceSettingsLogic } from './sourceSettingsLogic'

export interface ProjectionEditorLogicProps {
    id: string
    tabId?: string
}

export type DraftTableMap = Record<string, DirectPostgresProjectionTableConfig>

function deduplicate(values: string[]): string[] {
    return Array.from(new Set(values))
}

function normalizeCustomFields(fields: DirectPostgresProjectionCustomField[]): DirectPostgresProjectionCustomField[] {
    return fields
        .map((field) => ({
            name: field.name.trim(),
            expression: field.expression.trim(),
        }))
        .filter((field) => field.name || field.expression)
}

function normalizeForeignKeys(fields: DirectPostgresProjectionForeignKey[]): DirectPostgresProjectionForeignKey[] {
    return fields
        .map((field) => ({
            column: field.column.trim(),
            target_table: field.target_table.trim(),
            target_column: field.target_column.trim(),
        }))
        .filter((field) => field.column || field.target_table || field.target_column)
}

function normalizeDraftTable(table: DirectPostgresProjectionTableConfig): DirectPostgresProjectionTableConfig {
    return {
        source_name: table.source_name,
        source_catalog: table.source_catalog ?? null,
        source_schema: table.source_schema ?? null,
        source_table_name: table.source_table_name ?? null,
        enabled: !!table.enabled,
        query_name: table.query_name.trim(),
        removed_fields: deduplicate(table.removed_fields.map((field) => field.trim()).filter(Boolean)).sort(),
        custom_fields: normalizeCustomFields(table.custom_fields),
        foreign_keys: normalizeForeignKeys(table.foreign_keys),
    }
}

function normalizeDraftTableMap(draftTables: DraftTableMap): DraftTableMap {
    return Object.fromEntries(
        Object.entries(draftTables)
            .sort(([schemaA], [schemaB]) => schemaA.localeCompare(schemaB))
            .map(([schemaId, table]) => [schemaId, normalizeDraftTable(table)])
    )
}

function getProjectedQueryName(schema: ExternalDataSourceSchemaWithProjectionMetadata): string {
    return schema.schema_metadata?.query_name?.trim() || schema.table?.name?.trim() || schema.name
}

function buildDraftTable(
    schema: ExternalDataSourceSchemaWithProjectionMetadata
): DirectPostgresProjectionTableConfig | null {
    const rawMetadata = getRawProjectionSchemaMetadata(schema)
    if (!rawMetadata) {
        return null
    }

    const rawColumns = rawMetadata.columns ?? []
    const effectiveColumns = schema.schema_metadata?.columns ?? rawColumns
    const effectiveColumnNames = new Set(effectiveColumns.map((column) => column.name))

    return {
        source_name: schema.name,
        source_catalog: rawMetadata.source_catalog ?? null,
        source_schema: rawMetadata.source_schema ?? null,
        source_table_name: rawMetadata.source_table_name ?? null,
        enabled: schema.should_sync,
        query_name: getProjectedQueryName(schema),
        removed_fields: rawColumns
            .map((column) => column.name)
            .filter((columnName) => !effectiveColumnNames.has(columnName)),
        custom_fields: schema.schema_metadata?.custom_fields ?? [],
        foreign_keys: schema.schema_metadata?.foreign_keys ?? [],
    }
}

function buildDraftTables(source: ExternalDataSourceWithProjectionMetadata | null): DraftTableMap {
    if (!source?.schemas) {
        return {}
    }

    return Object.fromEntries(
        source.schemas
            .map((schema) => [schema.id, buildDraftTable(schema)] as const)
            .filter((entry): entry is [string, DirectPostgresProjectionTableConfig] => !!entry[1])
    )
}

export const projectionEditorLogic = kea<projectionEditorLogicType>([
    props({} as ProjectionEditorLogicProps),
    key(({ id, tabId }) => (tabId ? `${id}-${tabId}` : id)),
    path((key) => ['scenes', 'data-warehouse', 'settings', 'source', 'projectionEditorLogic', key]),
    actions({
        loadSource: true,
        syncProjectionState: (source: ExternalDataSource | null, force = false) => ({ source, force }),
        setProjectionDrafts: (draftTables: DraftTableMap) => ({ draftTables }),
        clearProjectionDrafts: true,
        resetProjectionDrafts: true,
        setDraftQueryName: (schemaId: string, queryName: string) => ({ schemaId, queryName }),
        setDraftEnabled: (schemaId: string, enabled: boolean) => ({ schemaId, enabled }),
        toggleRemovedField: (schemaId: string, fieldName: string) => ({ schemaId, fieldName }),
        addCustomField: (schemaId: string) => ({ schemaId }),
        updateCustomField: (
            schemaId: string,
            index: number,
            key: keyof DirectPostgresProjectionCustomField,
            value: string
        ) => ({ schemaId, index, key, value }),
        removeCustomField: (schemaId: string, index: number) => ({ schemaId, index }),
        addForeignKey: (schemaId: string) => ({ schemaId }),
        updateForeignKey: (
            schemaId: string,
            index: number,
            key: keyof DirectPostgresProjectionForeignKey,
            value: string
        ) => ({ schemaId, index, key, value }),
        removeForeignKey: (schemaId: string, index: number) => ({ schemaId, index }),
        saveProjection: (activate: boolean) => ({ activate }),
        setProjectionSaving: (saving: boolean) => ({ saving }),
        setActivatingRevisionId: (revisionId: string | null) => ({ revisionId }),
        activateRevision: (revisionId: string) => ({ revisionId }),
    }),
    loaders(({ props }) => ({
        projectionRevisions: [
            [] as DirectPostgresProjectionRevision[],
            {
                loadProjectionRevisions: async () => {
                    return (await api.externalDataSources.getProjectionRevisions(
                        props.id
                    )) as DirectPostgresProjectionRevision[]
                },
            },
        ],
    })),
    reducers({
        draftTables: [
            {} as DraftTableMap,
            {
                setProjectionDrafts: (_, { draftTables }) => draftTables,
                clearProjectionDrafts: () => ({}),
                setDraftQueryName: (state, { schemaId, queryName }) => {
                    const table = state[schemaId]
                    if (!table) {
                        return state
                    }

                    return {
                        ...state,
                        [schemaId]: { ...table, query_name: queryName },
                    }
                },
                setDraftEnabled: (state, { schemaId, enabled }) => {
                    const table = state[schemaId]
                    if (!table) {
                        return state
                    }

                    return {
                        ...state,
                        [schemaId]: { ...table, enabled },
                    }
                },
                toggleRemovedField: (state, { schemaId, fieldName }) => {
                    const table = state[schemaId]
                    if (!table) {
                        return state
                    }

                    const removedFields = table.removed_fields.includes(fieldName)
                        ? table.removed_fields.filter((field) => field !== fieldName)
                        : [...table.removed_fields, fieldName]

                    return {
                        ...state,
                        [schemaId]: { ...table, removed_fields: removedFields },
                    }
                },
                addCustomField: (state, { schemaId }) => {
                    const table = state[schemaId]
                    if (!table) {
                        return state
                    }

                    return {
                        ...state,
                        [schemaId]: {
                            ...table,
                            custom_fields: [...table.custom_fields, { name: '', expression: '' }],
                        },
                    }
                },
                updateCustomField: (state, { schemaId, index, key, value }) => {
                    const table = state[schemaId]
                    if (!table) {
                        return state
                    }

                    return {
                        ...state,
                        [schemaId]: {
                            ...table,
                            custom_fields: table.custom_fields.map((field, fieldIndex) =>
                                fieldIndex === index ? { ...field, [key]: value } : field
                            ),
                        },
                    }
                },
                removeCustomField: (state, { schemaId, index }) => {
                    const table = state[schemaId]
                    if (!table) {
                        return state
                    }

                    return {
                        ...state,
                        [schemaId]: {
                            ...table,
                            custom_fields: table.custom_fields.filter((_, fieldIndex) => fieldIndex !== index),
                        },
                    }
                },
                addForeignKey: (state, { schemaId }) => {
                    const table = state[schemaId]
                    if (!table) {
                        return state
                    }

                    return {
                        ...state,
                        [schemaId]: {
                            ...table,
                            foreign_keys: [...table.foreign_keys, { column: '', target_table: '', target_column: '' }],
                        },
                    }
                },
                updateForeignKey: (state, { schemaId, index, key, value }) => {
                    const table = state[schemaId]
                    if (!table) {
                        return state
                    }

                    return {
                        ...state,
                        [schemaId]: {
                            ...table,
                            foreign_keys: table.foreign_keys.map((field, fieldIndex) =>
                                fieldIndex === index ? { ...field, [key]: value } : field
                            ),
                        },
                    }
                },
                removeForeignKey: (state, { schemaId, index }) => {
                    const table = state[schemaId]
                    if (!table) {
                        return state
                    }

                    return {
                        ...state,
                        [schemaId]: {
                            ...table,
                            foreign_keys: table.foreign_keys.filter((_, fieldIndex) => fieldIndex !== index),
                        },
                    }
                },
            },
        ],
        baselineDraftTables: [
            {} as DraftTableMap,
            {
                setProjectionDrafts: (_, { draftTables }) => draftTables,
                clearProjectionDrafts: () => ({}),
            },
        ],
        projectionSaving: [
            false,
            {
                saveProjection: () => true,
                setProjectionSaving: (_, { saving }) => saving,
            },
        ],
        activatingRevisionId: [
            null as string | null,
            {
                activateRevision: (_, { revisionId }) => revisionId,
                setActivatingRevisionId: (_, { revisionId }) => revisionId,
            },
        ],
    }),
    selectors({
        source: [
            () => [
                (state: any, props: ProjectionEditorLogicProps) =>
                    sourceSettingsLogic({ id: props.id, tabId: props.tabId }).selectors.source(state),
            ],
            (source: ExternalDataSource | null): ExternalDataSource | null => source,
        ],
        sourceLoading: [
            () => [
                (state: any, props: ProjectionEditorLogicProps) =>
                    sourceSettingsLogic({ id: props.id, tabId: props.tabId }).selectors.sourceLoading(state),
            ],
            (sourceLoading: boolean): boolean => sourceLoading,
        ],
        projectionSource: [
            (s) => [s.source],
            (source: ExternalDataSource | null): ExternalDataSourceWithProjectionMetadata | null =>
                source as ExternalDataSourceWithProjectionMetadata | null,
        ],
        projectionSchemas: [
            (s) => [s.projectionSource],
            (source): ExternalDataSourceSchemaWithProjectionMetadata[] =>
                source?.schemas?.filter((schema) => !!getRawProjectionSchemaMetadata(schema)) ?? [],
        ],
        activeProjectionRevision: [
            (s) => [s.projectionRevisions],
            (projectionRevisions): DirectPostgresProjectionRevision | null =>
                projectionRevisions.find((revision) => revision.is_active) ?? null,
        ],
        isProjectionDirty: [
            (s) => [s.draftTables, s.baselineDraftTables],
            (draftTables, baselineDraftTables): boolean =>
                !objectsEqual(normalizeDraftTableMap(draftTables), normalizeDraftTableMap(baselineDraftTables)),
        ],
    }),
    listeners(({ actions, values, props }) => ({
        loadSource: async () => {
            sourceSettingsLogic({ id: props.id, tabId: props.tabId }).actions.loadSource()
        },
        syncProjectionState: async ({ source, force }) => {
            const draftTables = buildDraftTables(source as ExternalDataSourceWithProjectionMetadata | null)
            if (force || !values.isProjectionDirty || Object.keys(values.draftTables).length === 0) {
                actions.setProjectionDrafts(draftTables)
            }
        },
        resetProjectionDrafts: async () => {
            actions.setProjectionDrafts(buildDraftTables(values.projectionSource))
        },
        saveProjection: async ({ activate }) => {
            if (!values.projectionSchemas.length) {
                actions.setProjectionSaving(false)
                return
            }

            try {
                const tables = values.projectionSchemas
                    .map((schema) => values.draftTables[schema.id] ?? buildDraftTable(schema))
                    .filter((table): table is DirectPostgresProjectionTableConfig => !!table)
                    .map(normalizeDraftTable)

                const revisions = (await api.externalDataSources.createProjectionRevision(props.id, {
                    activate,
                    tables,
                })) as DirectPostgresProjectionRevision[]

                actions.loadProjectionRevisionsSuccess(revisions)
                actions.setProjectionDrafts(values.draftTables)

                if (activate) {
                    sourceSettingsLogic({ id: props.id, tabId: props.tabId }).actions.loadSource()
                }

                lemonToast.success(activate ? 'Projection revision saved and activated' : 'Projection revision saved')
            } catch (error: any) {
                lemonToast.error(error?.message ?? 'Unable to save projection revision')
            } finally {
                actions.setProjectionSaving(false)
            }
        },
        activateRevision: async ({ revisionId }) => {
            try {
                await api.externalDataSources.activateProjectionRevision(props.id, revisionId)
                actions.setActivatingRevisionId(null)
                actions.clearProjectionDrafts()
                actions.loadProjectionRevisions()
                sourceSettingsLogic({ id: props.id, tabId: props.tabId }).actions.loadSource()
                lemonToast.success('Projection revision activated')
            } catch (error: any) {
                actions.setActivatingRevisionId(null)
                lemonToast.error(error?.message ?? 'Unable to activate projection revision')
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadProjectionRevisions()
    }),
])
