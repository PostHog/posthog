import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { IconBolt, IconDatabase, IconDocument, IconEndpoints, IconFolder, IconPlug, IconPlus } from '@posthog/icons'
import { LemonMenuItem } from '@posthog/lemon-ui'
import { Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { TreeItem } from 'lib/components/DatabaseTableTree/DatabaseTableTree'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTreeRef, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { createFuse, IFuseOptions } from 'lib/utils/fuseSearch'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { POSTHOG_WAREHOUSE } from 'scenes/data-warehouse/editor/connectionSelectorLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaEndpointTable,
    DatabaseSchemaField,
    DatabaseSchemaManagedViewTable,
    DatabaseSchemaTable,
} from '~/queries/schema/schema-general'
import {
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryDraft,
    DataWarehouseSavedQueryFolder,
    DataWarehouseViewLink,
    QueryTabState,
} from '~/types'

import { SourceIcon, mapUrlToProvider } from 'products/data_warehouse/frontend/shared/components/SourceIcon'
import { joinsLogic } from 'products/data_warehouse/frontend/shared/logics/joinsLogic'
import { sourceManagementLogic } from 'products/data_warehouse/frontend/shared/logics/sourceManagementLogic'

import { dataWarehouseViewsLogic } from '../../saved_queries/dataWarehouseViewsLogic'
import { viewLinkLogic } from '../../viewLinkLogic'
import { draftsLogic } from '../draftsLogic'
import type { queryDatabaseLogicType } from './queryDatabaseLogicType'

export type EditorSidebarTreeRef = React.RefObject<LemonTreeRef> | null

export interface FuseSearchMatch {
    // kea-typegen has a problem importing Fuse itself, so we have to duplicate this type
    indices: readonly [number, number][]
    key: string
}

const isLazyNodeId = (id: string): boolean => {
    return id.startsWith('lazy-') || id.includes('-lazy-')
}

const isDataWarehouseTable = (
    table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery
): table is DatabaseSchemaDataWarehouseTable => {
    return 'type' in table && table.type === 'data_warehouse'
}

const isPostHogTable = (
    table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery
): table is DatabaseSchemaTable => {
    return 'type' in table && table.type === 'posthog'
}

const isSystemTable = (
    table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery
): table is DatabaseSchemaTable => {
    return 'type' in table && table.type === 'system'
}

const isViewTable = (
    table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery
): table is DataWarehouseSavedQuery => {
    // Use status as it's unique to DataWarehouseSavedQuery and always included in API responses
    return 'status' in table
}

const isManagedViewTable = (
    table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery
): table is DatabaseSchemaManagedViewTable => {
    return 'type' in table && table.type === 'managed_view'
}

export const isJoined = (field: DatabaseSchemaField): boolean => {
    return field.type === 'view' || field.type === 'lazy_table'
}

const getSavedQuerySchemaTable = (
    view: DataWarehouseSavedQuery,
    allTablesMap: Record<string, DatabaseSchemaTable>
): DatabaseSchemaTable | undefined => {
    const lookupKey = normalizeTableLookupKey(view.name)
    const schemaTable = lookupKey ? allTablesMap[lookupKey] : undefined

    if (schemaTable?.type === 'view' || schemaTable?.type === 'materialized_view') {
        return schemaTable
    }

    return undefined
}

const FUSE_OPTIONS: IFuseOptions<any> = {
    keys: [{ name: 'name', weight: 2 }],
    ignoreLocation: true,
    includeMatches: true,
}

const posthogTablesFuse = createFuse<DatabaseSchemaTable>([], FUSE_OPTIONS)
const systemTablesFuse = createFuse<DatabaseSchemaTable>([], FUSE_OPTIONS)
const dataWarehouseTablesFuse = createFuse<DatabaseSchemaDataWarehouseTable>([], FUSE_OPTIONS)
const savedQueriesFuse = createFuse<DataWarehouseSavedQuery>([], FUSE_OPTIONS)
const savedQueryFoldersFuse = createFuse<DataWarehouseSavedQueryFolder>([], FUSE_OPTIONS)
const managedViewsFuse = createFuse<DatabaseSchemaManagedViewTable>([], FUSE_OPTIONS)
const draftsFuse = createFuse<DataWarehouseSavedQueryDraft>([], FUSE_OPTIONS)
const endpointsFuse = createFuse<DatabaseSchemaEndpointTable>([], FUSE_OPTIONS)
// Factory functions for creating tree nodes
type TableLookupEntry = {
    name: string
    fields: Record<string, DatabaseSchemaField>
}

type TableLookup = Record<string, TableLookupEntry>

const MAX_FIELD_TRAVERSAL_DEPTH = 10

type FieldTraversalOptions = {
    expandedLazyNodeIds?: Set<string>
    visitedColumnPaths?: Set<string>
    depth?: number
}

export type SearchTreeSourceContext = {
    allPosthogTables: DatabaseSchemaTable[]
    systemTables: DatabaseSchemaTable[]
    dataWarehouseTables: DatabaseSchemaDataWarehouseTable[]
    dataWarehouseSavedQueries: DataWarehouseSavedQuery[]
    dataWarehouseSavedQueryFolders: DataWarehouseSavedQueryFolder[]
    managedViews: DatabaseSchemaManagedViewTable[]
    allTablesMap: Record<string, DatabaseSchemaTable>
}

export type SearchTreeMatches = {
    relevantPosthogTables: [DatabaseSchemaTable, FuseSearchMatch[] | null][]
    relevantSystemTables: [DatabaseSchemaTable, FuseSearchMatch[] | null][]
    relevantDataWarehouseTables: [DatabaseSchemaDataWarehouseTable, FuseSearchMatch[] | null][]
    relevantSavedQueries: [DataWarehouseSavedQuery, FuseSearchMatch[] | null][]
    relevantSavedQueryFolders: [DataWarehouseSavedQueryFolder, FuseSearchMatch[] | null][]
    relevantManagedViews: [DatabaseSchemaManagedViewTable, FuseSearchMatch[] | null][]
    relevantDrafts: [DataWarehouseSavedQueryDraft, FuseSearchMatch[] | null][]
    relevantEndpointTables: [DatabaseSchemaEndpointTable, FuseSearchMatch[] | null][]
}

export type TreeDataContext = {
    allPosthogTables: DatabaseSchemaTable[]
    posthogTables: DatabaseSchemaTable[]
    systemTables: DatabaseSchemaTable[]
    dataWarehouseTables: DatabaseSchemaDataWarehouseTable[]
    dataWarehouseSavedQueries: DataWarehouseSavedQuery[]
    dataWarehouseSavedQueryFolders: DataWarehouseSavedQueryFolder[]
    managedViews: DatabaseSchemaManagedViewTable[]
    latestEndpointTables: DatabaseSchemaEndpointTable[]
    allTablesMap: Record<string, DatabaseSchemaTable>
}

const DEFAULT_EXPANDED_FOLDERS = ['sources', 'views', 'managed-views'] as string[]
const EXPANDED_FOLDERS_DEFAULT_KEY = '__default__'

const normalizeTableLookupKey = (tableName?: string | null): string | null => {
    if (!tableName) {
        return null
    }

    return tableName.replaceAll('`', '')
}

const getPrimaryKeyName = (tableName: string, fields: DatabaseSchemaField[]): string | null => {
    const fieldNames = new Set(fields.map((field) => field.name))
    const baseTableName = tableName.split('.').pop() ?? tableName
    const candidates = ['id', `${baseTableName}_id`, 'uuid']

    for (const candidate of candidates) {
        if (fieldNames.has(candidate)) {
            return candidate
        }
    }

    return null
}

const sortFieldsWithPrimary = (tableName: string, fields: DatabaseSchemaField[]): DatabaseSchemaField[] => {
    const primaryKeyName = getPrimaryKeyName(tableName, fields)

    return [...fields].sort((a, b) => {
        if (primaryKeyName && a.name === primaryKeyName) {
            return -1
        }
        if (primaryKeyName && b.name === primaryKeyName) {
            return 1
        }
        const aIsVirtual = a.name.startsWith('$')
        const bIsVirtual = b.name.startsWith('$')
        if (aIsVirtual !== bIsVirtual) {
            return aIsVirtual ? 1 : -1
        }
        return a.name.localeCompare(b.name)
    })
}

const shouldHideField = (field: DatabaseSchemaField): boolean => {
    return field.name === 'team_id' && field.type === 'unknown'
}

const shouldHideFieldName = (fieldName: string): boolean => {
    return fieldName === 'team_id'
}

const shouldUseDirectConnectionTree = (connectionId: string | null): boolean => {
    return !!connectionId && connectionId !== POSTHOG_WAREHOUSE
}

const createColumnNode = (
    tableName: string,
    field: DatabaseSchemaField,
    columnPath: string,
    isSearch = false
): TreeDataItem => ({
    id: `${isSearch ? 'search-' : ''}col-${tableName}-${columnPath}`,
    name: field.name,
    type: 'node',
    record: {
        type: 'column',
        columnName: columnPath,
        field,
        table: tableName,
    },
})

const createVirtualTableField = (
    fieldName: string,
    parentField: DatabaseSchemaField,
    tableLookup?: TableLookup
): DatabaseSchemaField => {
    const referencedTable = parentField.table ? tableLookup?.[parentField.table] : undefined
    const referencedField = referencedTable?.fields?.[fieldName]

    if (referencedField) {
        return referencedField
    }

    return {
        name: fieldName,
        hogql_value: fieldName,
        type: 'unknown',
        schema_valid: true,
    }
}

const formatTraversalChain = (chain?: (string | number)[]): string | null => {
    if (!chain || chain.length === 0) {
        return null
    }

    return chain.map((segment) => String(segment)).join('.')
}

const resolveFieldTraverserTarget = (
    tableName: string,
    field: DatabaseSchemaField,
    tableLookup?: TableLookup,
    visitedChains: Set<string> = new Set()
): DatabaseSchemaField | null => {
    if (!field.chain || !tableLookup) {
        return null
    }

    const baseTable = tableLookup[tableName]
    if (!baseTable) {
        return null
    }

    let currentTable: TableLookupEntry | null = baseTable
    let currentField: DatabaseSchemaField | null = null
    let index = 0

    while (index < field.chain.length) {
        const segment: string | number = field.chain[index]
        const segmentKey = String(segment)

        if (segmentKey === '..') {
            return null
        }

        if (!currentField) {
            const nextField: DatabaseSchemaField | undefined = currentTable?.fields?.[segmentKey]
            if (!nextField) {
                return null
            }
            currentField = nextField
            index += 1
            continue
        }

        if (currentField.type === 'lazy_table') {
            currentTable = currentField.table ? (tableLookup[currentField.table] ?? null) : null
            currentField = null
            continue
        }

        if (currentField.type === 'virtual_table') {
            if (!currentField.fields?.includes(segmentKey)) {
                return null
            }
            currentField = createVirtualTableField(segmentKey, currentField, tableLookup)
            index += 1
            continue
        }

        if (currentField.type === 'field_traverser' && currentField.chain) {
            const chainKey = formatTraversalChain(currentField.chain)
            if (!chainKey || visitedChains.has(chainKey)) {
                return null
            }
            visitedChains.add(chainKey)
            currentField = resolveFieldTraverserTarget(tableName, currentField, tableLookup, visitedChains)
            if (!currentField) {
                return null
            }
            continue
        }

        return null
    }

    if (currentField?.type === 'field_traverser') {
        return resolveFieldTraverserTarget(tableName, currentField, tableLookup, visitedChains) ?? currentField
    }

    return currentField
}

const createLazyTablePlaceholderNode = (lazyNodeId: string): TreeDataItem => {
    return {
        id: `${lazyNodeId}-placeholder/`,
        name: 'Loading...',
        displayName: <>Loading...</>,
        icon: <Spinner />,
        disableSelect: true,
        type: 'loading-indicator',
    }
}

const createLazyTableEmptyNode = (lazyNodeId: string): TreeDataItem => {
    return {
        id: `${lazyNodeId}-empty/`,
        name: 'Empty folder',
        type: 'empty-folder',
        record: {
            type: 'empty-folder',
        },
    }
}

const createLazyTableChildren = (
    tableName: string,
    field: DatabaseSchemaField,
    isSearch: boolean,
    columnPath: string,
    tableLookup: TableLookup | undefined,
    options: FieldTraversalOptions
): TreeDataItem[] => {
    const normalizedTableName = normalizeTableLookupKey(field.table)
    const referencedTable = field.table
        ? (tableLookup?.[field.table] ?? (normalizedTableName ? tableLookup?.[normalizedTableName] : undefined))
        : undefined

    if (!referencedTable) {
        if (!field.fields) {
            return []
        }

        return field.fields
            .filter((childFieldName) => !shouldHideFieldName(childFieldName))
            .map((childFieldName) =>
                createFieldNode(
                    tableName,
                    {
                        name: childFieldName,
                        hogql_value: childFieldName,
                        type: 'unknown',
                        schema_valid: true,
                    },
                    isSearch,
                    `${columnPath}.${childFieldName}`,
                    tableLookup,
                    options
                )
            )
    }

    if (field.fields?.length) {
        return field.fields
            .filter((childFieldName) => !shouldHideFieldName(childFieldName))
            .map((childFieldName) => {
                const childField =
                    referencedTable.fields[childFieldName] ??
                    ({
                        name: childFieldName,
                        hogql_value: childFieldName,
                        type: 'unknown',
                        schema_valid: true,
                    } as DatabaseSchemaField)

                if (shouldHideField(childField)) {
                    return null
                }

                return createFieldNode(
                    tableName,
                    childField,
                    isSearch,
                    `${columnPath}.${childField.name}`,
                    tableLookup,
                    options
                )
            })
            .filter((node): node is TreeDataItem => node !== null)
    }

    return Object.values(referencedTable.fields)
        .filter((childField) => !shouldHideField(childField))
        .map((childField) =>
            createFieldNode(tableName, childField, isSearch, `${columnPath}.${childField.name}`, tableLookup, options)
        )
}

const createViewTableChildren = (
    tableName: string,
    field: DatabaseSchemaField,
    isSearch: boolean,
    columnPath: string,
    tableLookup?: TableLookup,
    options?: FieldTraversalOptions
): TreeDataItem[] => {
    const normalizedTableName = normalizeTableLookupKey(field.table)
    const referencedTable = field.table
        ? (tableLookup?.[field.table] ?? (normalizedTableName ? tableLookup?.[normalizedTableName] : undefined))
        : undefined

    if (!referencedTable) {
        if (!field.fields) {
            return []
        }

        return field.fields
            .filter((childFieldName) => !shouldHideFieldName(childFieldName))
            .map((childFieldName) =>
                createFieldNode(
                    tableName,
                    {
                        name: childFieldName,
                        hogql_value: childFieldName,
                        type: 'unknown',
                        schema_valid: true,
                    },
                    isSearch,
                    `${columnPath}.${childFieldName}`,
                    tableLookup,
                    options
                )
            )
    }

    if (field.fields?.length) {
        return field.fields
            .filter((childFieldName) => !shouldHideFieldName(childFieldName))
            .map((childFieldName) => {
                const childField =
                    referencedTable.fields[childFieldName] ??
                    ({
                        name: childFieldName,
                        hogql_value: childFieldName,
                        type: 'unknown',
                        schema_valid: true,
                    } as DatabaseSchemaField)

                if (shouldHideField(childField)) {
                    return null
                }

                return createFieldNode(
                    tableName,
                    childField,
                    isSearch,
                    `${columnPath}.${childField.name}`,
                    tableLookup,
                    options
                )
            })
            .filter((node): node is TreeDataItem => node !== null)
    }

    const sortedFields = sortFieldsWithPrimary(referencedTable.name, Object.values(referencedTable.fields))
    return sortedFields
        .filter((childField) => !shouldHideField(childField))
        .map((childField) =>
            createFieldNode(tableName, childField, isSearch, `${columnPath}.${childField.name}`, tableLookup, options)
        )
}

const createTraversedLazyTableNode = (
    tableName: string,
    field: DatabaseSchemaField,
    traversedField: DatabaseSchemaField,
    isSearch: boolean,
    columnPath: string,
    tableLookup: TableLookup | undefined,
    options: FieldTraversalOptions
): TreeDataItem => {
    const lazyNodeId = `${isSearch ? 'search-' : ''}lazy-traverser-${tableName}-${columnPath}`
    const isExpanded = options?.expandedLazyNodeIds?.has(lazyNodeId)
    const lazyChildren = isExpanded
        ? createLazyTableChildren(tableName, traversedField, isSearch, columnPath, tableLookup, options)
        : []
    const children = isExpanded
        ? lazyChildren.length > 0
            ? lazyChildren
            : [createLazyTableEmptyNode(lazyNodeId)]
        : [createLazyTablePlaceholderNode(lazyNodeId)]

    return {
        id: lazyNodeId,
        name: field.name,
        type: 'node',
        record: {
            type: 'field-traverser',
            field,
            table: tableName,
            referencedTable: traversedField.table,
            traversedFieldType: 'lazy-table',
        },
        children,
    }
}

const createTraversedVirtualTableNode = (
    tableName: string,
    field: DatabaseSchemaField,
    traversedField: DatabaseSchemaField,
    isSearch: boolean,
    columnPath: string,
    tableLookup: TableLookup | undefined,
    options?: FieldTraversalOptions
): TreeDataItem => {
    const children =
        traversedField.fields
            ?.slice()
            .filter((fieldName) => !shouldHideFieldName(fieldName))
            .sort((a, b) => a.localeCompare(b))
            .map((fieldName) => {
                const childField = createVirtualTableField(fieldName, traversedField, tableLookup)
                if (shouldHideField(childField)) {
                    return null
                }
                return createFieldNode(
                    tableName,
                    childField,
                    isSearch,
                    `${columnPath}.${fieldName}`,
                    tableLookup,
                    options
                )
            })
            .filter((node): node is TreeDataItem => node !== null) ?? []

    return {
        id: `${isSearch ? 'search-' : ''}traverser-${tableName}-${columnPath}`,
        name: field.name,
        type: 'node',
        record: {
            type: 'field-traverser',
            field,
            table: tableName,
            traversedFieldType: 'virtual-table',
        },
        children,
    }
}

const createFieldNode = (
    tableName: string,
    field: DatabaseSchemaField,
    isSearch: boolean,
    columnPath: string,
    tableLookup?: TableLookup,
    options?: FieldTraversalOptions
): TreeDataItem => {
    const expandedLazyNodeIds = options?.expandedLazyNodeIds
    const visitedColumnPaths = options?.visitedColumnPaths ?? new Set<string>()
    const depth = options?.depth ?? 0
    const columnKey = `${tableName}:${columnPath}`

    if (visitedColumnPaths.has(columnKey) || depth >= MAX_FIELD_TRAVERSAL_DEPTH) {
        return createColumnNode(tableName, field, columnPath, isSearch)
    }

    const nextVisitedColumnPaths = new Set(visitedColumnPaths)
    nextVisitedColumnPaths.add(columnKey)
    const nextOptions: FieldTraversalOptions = {
        expandedLazyNodeIds,
        visitedColumnPaths: nextVisitedColumnPaths,
        depth: depth + 1,
    }
    if (field.type === 'virtual_table') {
        const children =
            field.fields
                ?.slice()
                .filter((fieldName) => !shouldHideFieldName(fieldName))
                .sort((a, b) => a.localeCompare(b))
                .map((fieldName) => {
                    const childField = createVirtualTableField(fieldName, field, tableLookup)
                    if (shouldHideField(childField)) {
                        return null
                    }
                    return createFieldNode(
                        tableName,
                        childField,
                        isSearch,
                        `${columnPath}.${fieldName}`,
                        tableLookup,
                        nextOptions
                    )
                })
                .filter((node): node is TreeDataItem => node !== null) ?? []

        return {
            id: `${isSearch ? 'search-' : ''}virtual-${tableName}-${columnPath}`,
            name: field.name,
            type: 'node',
            record: {
                type: 'virtual-table',
                field,
                table: tableName,
            },
            children,
        }
    }

    if (field.type === 'field_traverser') {
        const traversedField = resolveFieldTraverserTarget(tableName, field, tableLookup)
        if (traversedField?.type === 'lazy_table' && expandedLazyNodeIds) {
            return createTraversedLazyTableNode(
                tableName,
                field,
                traversedField,
                isSearch,
                columnPath,
                tableLookup,
                nextOptions
            )
        }

        if (traversedField?.type === 'virtual_table') {
            return createTraversedVirtualTableNode(
                tableName,
                field,
                traversedField,
                isSearch,
                columnPath,
                tableLookup,
                nextOptions
            )
        }
    }

    if (field.type === 'view' || field.type === 'materialized_view') {
        const children = createViewTableChildren(tableName, field, isSearch, columnPath, tableLookup, nextOptions)

        return {
            id: `${isSearch ? 'search-' : ''}view-table-${tableName}-${columnPath}`,
            name: field.name,
            type: 'node',
            record: {
                type: 'view-table',
                field,
                table: tableName,
                referencedTable: field.table,
                traversedFieldType: field.type,
            },
            children,
        }
    }

    if (field.type === 'lazy_table') {
        const lazyNodeId = `${isSearch ? 'search-' : ''}lazy-${tableName}-${columnPath}`
        const isExpanded = expandedLazyNodeIds ? expandedLazyNodeIds.has(lazyNodeId) : false
        const lazyExpandedIds = expandedLazyNodeIds ?? new Set<string>()
        const lazyChildren = isExpanded
            ? createLazyTableChildren(tableName, field, isSearch, columnPath, tableLookup, {
                  ...nextOptions,
                  expandedLazyNodeIds: lazyExpandedIds,
              })
            : []

        const children = isExpanded
            ? lazyChildren.length > 0
                ? lazyChildren
                : [createLazyTableEmptyNode(lazyNodeId)]
            : [createLazyTablePlaceholderNode(lazyNodeId)]

        return {
            id: lazyNodeId,
            name: field.name,
            type: 'node',
            record: {
                type: 'lazy-table',
                field,
                table: tableName,
                referencedTable: field.table,
            },
            children,
        }
    }

    return createColumnNode(tableName, field, columnPath, isSearch)
}

const createSavedQueryLookupEntry = (view: DataWarehouseSavedQuery): TableLookupEntry => {
    return {
        name: view.name,
        fields: Object.fromEntries(view.columns.map((column) => [column.name, column])),
    }
}

const createTableLookup = ({
    posthogTables,
    systemTables,
    dataWarehouseTables,
    dataWarehouseSavedQueries,
    managedViews,
    savedQuerySchemaTables,
}: {
    posthogTables: DatabaseSchemaTable[]
    systemTables: DatabaseSchemaTable[]
    dataWarehouseTables: DatabaseSchemaDataWarehouseTable[]
    dataWarehouseSavedQueries: DataWarehouseSavedQuery[]
    managedViews: DatabaseSchemaManagedViewTable[]
    savedQuerySchemaTables?: Record<string, DatabaseSchemaTable>
}): TableLookup => {
    return Object.fromEntries(
        [
            ...posthogTables.map((table) => [table.name, { name: table.name, fields: table.fields }]),
            ...systemTables.map((table) => [table.name, { name: table.name, fields: table.fields }]),
            ...dataWarehouseTables.map((table) => [table.name, { name: table.name, fields: table.fields }]),
            ...dataWarehouseSavedQueries.map((view) => {
                const schemaTable = savedQuerySchemaTables
                    ? getSavedQuerySchemaTable(view, savedQuerySchemaTables)
                    : undefined

                return schemaTable
                    ? [view.name, { name: view.name, fields: schemaTable.fields }]
                    : [view.name, createSavedQueryLookupEntry(view)]
            }),
            ...managedViews.map((view) => [view.name, { name: view.name, fields: view.fields }]),
        ].map(([name, entry]) => [normalizeTableLookupKey(name ? String(name) : null) ?? name, entry])
    )
}

const createTableNode = (
    table: DatabaseSchemaTable | DatabaseSchemaDataWarehouseTable,
    matches: FuseSearchMatch[] | null = null,
    isSearch = false,
    tableLookup?: TableLookup,
    options?: {
        expandedLazyNodeIds?: Set<string>
    }
): TreeDataItem => {
    const tableChildren: TreeDataItem[] = []

    if ('fields' in table) {
        sortFieldsWithPrimary(table.name, Object.values(table.fields))
            .filter((field) => !shouldHideField(field))
            .forEach((field: DatabaseSchemaField) => {
                tableChildren.push(
                    createFieldNode(table.name, field, isSearch, field.name, tableLookup, {
                        expandedLazyNodeIds: options?.expandedLazyNodeIds,
                    })
                )
            })
    }

    const tableId = `${isSearch ? 'search-' : ''}table-${table.name}`
    return {
        id: tableId,
        name: table.name,
        type: 'node',
        icon: <IconDatabase />,
        record: {
            type: 'table',
            table: table,
            row_count: table.row_count,
            ...(matches && { searchMatches: matches }),
        },
        children: tableChildren,
    }
}

const createDraftNode = (
    draft: DataWarehouseSavedQueryDraft,
    matches: FuseSearchMatch[] | null = null,
    isSearch = false
): TreeDataItem => {
    return {
        id: `${isSearch ? 'search-' : ''}draft-${draft.id}`,
        name: draft.name,
        type: 'node',
        icon: <IconDocument />,
        record: {
            id: draft.id,
            type: 'draft',
            draft: draft,
            ...(matches && { searchMatches: matches }),
        },
    }
}

const createViewFolderNode = (
    folder: DataWarehouseSavedQueryFolder,
    children: TreeDataItem[],
    matches: FuseSearchMatch[] | null = null,
    isSearch = false
): TreeDataItem => {
    return {
        id: `${isSearch ? 'search-' : ''}view-folder-${folder.id}`,
        name: folder.name,
        type: 'node',
        record: {
            type: 'folder',
            folderType: 'view-folder',
            folder,
            ...(matches && { searchMatches: matches }),
        },
        children:
            children.length > 0
                ? children
                : [
                      {
                          id: `${isSearch ? 'search-' : ''}view-folder-${folder.id}-empty/`,
                          name: 'Empty folder',
                          type: 'empty-folder',
                          record: {
                              type: 'empty-folder',
                          },
                      },
                  ],
    }
}

const createViewNode = (
    view: DataWarehouseSavedQuery,
    matches: FuseSearchMatch[] | null = null,
    isSearch = false,
    tableLookup?: TableLookup,
    options?: {
        expandedLazyNodeIds?: Set<string>
    },
    schemaTable?: DatabaseSchemaTable
): TreeDataItem => {
    const viewChildren: TreeDataItem[] = []
    const isMaterializedView = view.is_materialized === true
    const isManagedViewsetView = view.managed_viewset_kind !== null
    const isManagedView = 'type' in view && view.type === 'managed_view'
    const viewFields =
        schemaTable && Object.keys(schemaTable.fields).length > 0 ? Object.values(schemaTable.fields) : view.columns

    sortFieldsWithPrimary(view.name, viewFields)
        .filter((column) => !shouldHideField(column))
        .forEach((column: DatabaseSchemaField) => {
            viewChildren.push(
                createFieldNode(view.name, column, isSearch, column.name, tableLookup, {
                    expandedLazyNodeIds: options?.expandedLazyNodeIds,
                })
            )
        })

    const viewId = `${isSearch ? 'search-' : ''}view-${view.id}`

    return {
        id: viewId,
        name: view.name,
        type: 'node',
        icon: isManagedViewsetView ? (
            <IconBolt />
        ) : isManagedView || isMaterializedView ? (
            <IconDatabase />
        ) : (
            <IconDocument />
        ),
        record: {
            type: 'view',
            view: view,
            isSavedQuery: !isManagedView,
            ...(matches && { searchMatches: matches }),
        },
        children: viewChildren,
    }
}

const createManagedViewNode = (
    managedView: DatabaseSchemaManagedViewTable,
    matches: FuseSearchMatch[] | null = null,
    isSearch = false,
    tableLookup?: TableLookup,
    options?: {
        expandedLazyNodeIds?: Set<string>
    }
): TreeDataItem => {
    const viewChildren: TreeDataItem[] = []

    sortFieldsWithPrimary(managedView.name, Object.values(managedView.fields))
        .filter((field) => !shouldHideField(field))
        .forEach((field: DatabaseSchemaField) => {
            viewChildren.push(
                createFieldNode(managedView.name, field, isSearch, field.name, tableLookup, {
                    expandedLazyNodeIds: options?.expandedLazyNodeIds,
                })
            )
        })

    const managedViewId = `${isSearch ? 'search-' : ''}managed-view-${managedView.id}`

    return {
        id: managedViewId,
        name: managedView.name,
        type: 'node',
        icon: <IconDatabase />,
        record: {
            type: 'managed-view',
            view: managedView,
            ...(matches && { searchMatches: matches }),
        },
        children: viewChildren,
    }
}

const createEndpointNode = (
    endpointTable: DatabaseSchemaEndpointTable,
    matches: FuseSearchMatch[] | null = null,
    isSearch = false,
    tableLookup?: TableLookup,
    options?: { expandedLazyNodeIds?: Set<string> }
): TreeDataItem => {
    const children: TreeDataItem[] = []
    sortFieldsWithPrimary(endpointTable.name, Object.values(endpointTable.fields))
        .filter((column) => !shouldHideField(column))
        .forEach((column) => {
            children.push(
                createFieldNode(endpointTable.name, column, isSearch, column.name, tableLookup, {
                    expandedLazyNodeIds: options?.expandedLazyNodeIds,
                })
            )
        })

    const displayName = endpointTable.name.replace(/_v\d+$/, '')

    return {
        id: `${isSearch ? 'search-' : ''}endpoint-${endpointTable.id}`,
        name: displayName,
        type: 'node',
        icon: <IconEndpoints />,
        record: {
            type: 'endpoint',
            table: endpointTable,
            tableName: endpointTable.name,
            ...(matches && { searchMatches: matches }),
        },
        children,
    }
}

const createSourceFolderNode = (
    sourceType: string,
    tables: (DatabaseSchemaTable | DatabaseSchemaDataWarehouseTable)[],
    matches: [any, FuseSearchMatch[] | null][] = [],
    isSearch = false,
    tableLookup?: TableLookup,
    options?: {
        expandedLazyNodeIds?: Set<string>
    }
): TreeDataItem => {
    const sourceChildren: TreeDataItem[] = []

    if (isSearch && matches.length > 0) {
        matches.forEach(([table, tableMatches]) => {
            sourceChildren.push(createTableNode(table, tableMatches, true, tableLookup, options))
        })
    } else {
        tables.forEach((table) => {
            sourceChildren.push(createTableNode(table, null, false, tableLookup, options))
        })
    }

    const sourceFolderId = isSearch
        ? `search-${sourceType === 'PostHog' ? 'posthog' : sourceType}`
        : `source-${sourceType === 'PostHog' ? 'posthog' : sourceType}`

    return {
        id: sourceFolderId,
        name: sourceType,
        type: 'node',
        icon: (
            <SourceIcon
                type={
                    sourceType === 'Self-managed' && (tables.length > 0 || matches.length > 0)
                        ? mapUrlToProvider(
                              tables.length > 0
                                  ? (tables[0] as DatabaseSchemaDataWarehouseTable).url_pattern
                                  : (matches[0][0] as DatabaseSchemaDataWarehouseTable).url_pattern
                          )
                        : sourceType
                }
                size="xsmall"
                disableTooltip
            />
        ),
        record: {
            type: 'source-folder',
            sourceType,
        },
        children: sourceChildren,
    }
}

const createTopLevelFolderNode = (
    type: 'sources' | 'views' | 'managed-views' | 'drafts',
    children: TreeDataItem[],
    isSearch = false,
    icon?: JSX.Element
): TreeDataItem => {
    let finalChildren = children

    // Add empty folder child if views folder is empty
    if (type === 'views' && children.length === 0) {
        finalChildren = [
            {
                id: `${isSearch ? 'search-' : ''}views-folder-empty/`,
                name: 'Empty folder',
                type: 'empty-folder',
                record: {
                    type: 'empty-folder',
                },
            },
        ]
    }

    if (type === 'drafts' && children.length === 0) {
        finalChildren = [
            {
                id: `${isSearch ? 'search-' : ''}drafts-folder-empty/`,
                name: 'Empty folder',
                type: 'empty-folder',
                record: {
                    type: 'empty-folder',
                },
            },
        ]
    }

    if (type === 'managed-views' && children.length === 0) {
        finalChildren = [
            {
                id: `${isSearch ? 'search-' : ''}managed-views-folder-empty/`,
                name: 'Empty folder',
                type: 'empty-folder',
                record: {
                    type: 'empty-folder',
                },
            },
        ]
    }

    return {
        id: isSearch ? `search-${type}` : type,
        name:
            type === 'sources'
                ? 'Sources'
                : type === 'views'
                  ? 'Views'
                  : type === 'drafts'
                    ? 'Drafts'
                    : 'Managed Views',
        type: 'node',
        icon: icon,
        record: {
            type,
        },
        children: finalChildren,
    }
}

const flattenViewNodes = (nodes: TreeDataItem[], flattenedViews: TreeDataItem[]): void => {
    nodes.forEach((node) => {
        if (node.record?.type === 'view-table') {
            flattenedViews.push(node)
            return
        }

        if (node.record?.type === 'folder' && node.record?.folderType === 'view-folder') {
            flattenViewNodes(node.children ?? [], flattenedViews)
        }
    })
}

const getDirectConnectionSchemaName = (tableNode: TreeDataItem, defaultSchemaName?: string | null): string | null => {
    const tableName =
        tableNode.record?.type === 'table' ? (tableNode.record.table?.name ?? tableNode.name) : tableNode.name
    const dotIndex = tableName.indexOf('.')

    if (dotIndex > 0) {
        return tableName.slice(0, dotIndex)
    }

    if (defaultSchemaName && defaultSchemaName.trim()) {
        return defaultSchemaName.trim()
    }

    return null
}

const getDirectConnectionDisplayTableName = (tableNode: TreeDataItem): string => {
    const tableName =
        tableNode.record?.type === 'table' ? (tableNode.record.table?.name ?? tableNode.name) : tableNode.name
    const dotIndex = tableName.indexOf('.')

    return dotIndex > 0 ? tableName.slice(dotIndex + 1) : tableName
}

export const groupDirectConnectionTableNodesBySchema = (
    tableNodes: TreeDataItem[],
    isSearch: boolean,
    defaultSchemaName?: string | null
): TreeDataItem[] => {
    const tablesBySchema = new Map<string, TreeDataItem[]>()
    const ungroupedTables: TreeDataItem[] = []

    tableNodes.forEach((tableNode) => {
        const schemaName = getDirectConnectionSchemaName(tableNode, defaultSchemaName)

        if (!schemaName) {
            ungroupedTables.push(tableNode)
            return
        }

        const currentNodes = tablesBySchema.get(schemaName) ?? []
        currentNodes.push({
            ...tableNode,
            displayName: getDirectConnectionDisplayTableName(tableNode),
        })
        tablesBySchema.set(schemaName, currentNodes)
    })

    const schemaFolders = Array.from(tablesBySchema.entries())
        .sort(([leftSchema], [rightSchema]) => leftSchema.localeCompare(rightSchema))
        .map(([schemaName, schemaTables]) => ({
            id: `${isSearch ? 'search-' : ''}schema-${schemaName}`,
            name: schemaName,
            type: 'node' as const,
            icon: <IconFolder />,
            record: {
                type: 'source-folder',
                sourceType: schemaName,
            },
            children: [...schemaTables].sort((leftTable, rightTable) => leftTable.name.localeCompare(rightTable.name)),
        }))

    if (ungroupedTables.length > 0) {
        schemaFolders.push({
            id: `${isSearch ? 'search-' : ''}schema-ungrouped`,
            name: defaultSchemaName?.trim() || 'Tables',
            type: 'node',
            icon: <IconFolder />,
            record: {
                type: 'source-folder',
                sourceType: defaultSchemaName?.trim() || 'Tables',
            },
            children: [...ungroupedTables].sort((leftTable, rightTable) =>
                leftTable.name.localeCompare(rightTable.name)
            ),
        })
    }

    return schemaFolders
}

export const getDefaultExpandedRootIds = (connectionId: string | null, displayedTreeData: TreeDataItem[]): string[] => {
    if (!shouldUseDirectConnectionTree(connectionId)) {
        return []
    }

    return displayedTreeData
        .filter(
            (item) =>
                item.record?.type !== 'source-folder' ||
                item.children?.some((child) => child.type === 'loading-indicator')
        )
        .map((item) => item.id)
}

const getExpandedFoldersConnectionKey = (connectionId: string | null): string =>
    connectionId || EXPANDED_FOLDERS_DEFAULT_KEY

export const getInitialExpandedFolders = (connectionId: string | null, displayedTreeData: TreeDataItem[]): string[] => {
    if (!shouldUseDirectConnectionTree(connectionId)) {
        return [...DEFAULT_EXPANDED_FOLDERS]
    }

    const schemaFolderIds = displayedTreeData
        .filter((item) => item.record?.type === 'source-folder')
        .map((item) => item.id)

    return Array.from(
        new Set([
            ...DEFAULT_EXPANDED_FOLDERS,
            ...getDefaultExpandedRootIds(connectionId, displayedTreeData),
            ...schemaFolderIds,
        ])
    )
}

export const shouldInitializeDirectConnectionExpandedFolders = (
    displayedTreeData: TreeDataItem[],
    currentExpandedFolders?: string[]
): boolean => {
    if (currentExpandedFolders === undefined) {
        return true
    }

    const schemaFolderIds = displayedTreeData
        .filter((item) => item.record?.type === 'source-folder')
        .map((item) => item.id)

    if (schemaFolderIds.length === 0) {
        return false
    }

    const expandedFolderSet = new Set(currentExpandedFolders)
    const hasExpandedSchemaFolder = schemaFolderIds.some((folderId) => expandedFolderSet.has(folderId))
    const hasOnlyDefaultExpandedFolders =
        currentExpandedFolders.length === DEFAULT_EXPANDED_FOLDERS.length &&
        DEFAULT_EXPANDED_FOLDERS.every((folderId) => expandedFolderSet.has(folderId))

    return !hasExpandedSchemaFolder && hasOnlyDefaultExpandedFolders
}

const findTreePath = (items: TreeDataItem[], targetId: string, path: TreeDataItem[] = []): TreeDataItem[] | null => {
    for (const item of items) {
        const nextPath = [...path, item]

        if (item.id === targetId) {
            return nextPath
        }

        if (item.children) {
            const foundPath = findTreePath(item.children, targetId, nextPath)
            if (foundPath) {
                return foundPath
            }
        }
    }

    return null
}

const findTreeItem = (items: TreeDataItem[], targetId: string): TreeDataItem | null => {
    const path = findTreePath(items, targetId)
    return path ? path[path.length - 1] : null
}

const getFolderIdFromDropTarget = (items: TreeDataItem[], dropTargetId: string | null): string | null | undefined => {
    if (dropTargetId === '') {
        return null
    }

    const targetPath = dropTargetId ? findTreePath(items, dropTargetId) : null
    if (!targetPath) {
        return undefined
    }

    const enclosingViewFolder = [...targetPath]
        .reverse()
        .find((item) => item.record?.type === 'folder' && item.record?.folderType === 'view-folder')
    if (enclosingViewFolder?.record?.folder?.id) {
        return enclosingViewFolder.record.folder.id
    }

    const isInTopLevelViewsSection = targetPath.some((item) => item.record?.type === 'views')
    if (isInTopLevelViewsSection) {
        return null
    }

    return undefined
}

export const queryDatabaseLogic = kea<queryDatabaseLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'queryDatabaseLogic']),
    actions({
        selectSchema: (schema: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery) => ({
            schema,
        }),
        setExpandedFolders: (folderIds: string[], connectionId?: string | null) => ({ folderIds, connectionId }),
        setExpandedSearchFolders: (folderIds: string[]) => ({ folderIds }),
        toggleFolderOpen: (folderId: string, isExpanded: boolean) => ({ folderId, isExpanded }),
        setTreeRef: (ref: EditorSidebarTreeRef | null) => ({ ref }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        clearSearch: true,
        selectSourceTable: (tableName: string) => ({ tableName }),
        setSyncMoreNoticeDismissed: (dismissed: boolean) => ({ dismissed }),
        setEditingDraft: (draftId: string) => ({ draftId }),
        setPendingViewFolderOverride: (viewId: string, folderId: string | null) => ({ viewId, folderId }),
        clearPendingViewFolderOverride: (viewId: string) => ({ viewId }),
        clearPendingViewFolderOverrides: true,
        startDraggingView: (viewId: string) => ({ viewId }),
        setDraggedViewDropState: (folderId: string | null, isViewsSectionDrop: boolean) => ({
            folderId,
            isViewsSectionDrop,
        }),
        updateDraggedViewDropTarget: (dropTargetId: string | null) => ({ dropTargetId }),
        clearDraggedViewState: true,
        moveDraggedViewToDropTarget: (viewId: string, dropTargetId: string | null) => ({ viewId, dropTargetId }),
        openUnsavedQuery: (record: Record<string, any>) => ({ record }),
        deleteUnsavedQuery: (record: Record<string, any>) => ({ record }),
    }),
    connect(() => ({
        values: [
            joinsLogic,
            ['joins', 'joinsLoading'],
            databaseTableListLogic,
            [
                'allPosthogTables',
                'posthogTables',
                'dataWarehouseTables',
                'posthogTablesMap',
                'dataWarehouseTablesMap',
                'viewsMapById',
                'managedViews',
                'databaseLoading',
                'systemTables',
                'systemTablesMap',
                'allTablesMap',
                'latestEndpointTables',
                'connectionId',
            ],
            dataWarehouseViewsLogic,
            [
                'dataWarehouseSavedQueries',
                'dataWarehouseSavedQueryFolders',
                'dataWarehouseSavedQueryMapById',
                'dataWarehouseSavedQueriesLoading',
            ],
            draftsLogic,
            ['drafts', 'draftsResponseLoading', 'hasMoreDrafts'],
            sourceManagementLogic,
            ['dataWarehouseSources'],
            featureFlagLogic,
            ['featureFlags'],
            userLogic,
            ['user'],
        ],
        actions: [
            viewLinkLogic,
            ['toggleEditJoinModal', 'toggleJoinTableModal'],
            sourceManagementLogic,
            ['deleteJoin'],
            dataWarehouseViewsLogic,
            [
                'createDataWarehouseSavedQuerySuccess',
                'updateDataWarehouseSavedQuerySuccess',
                'updateDataWarehouseSavedQueryFailure',
                'updateDataWarehouseSavedQuery',
            ],
            draftsLogic,
            ['loadDrafts', 'renameDraft', 'loadMoreDrafts'],
        ],
    })),
    reducers({
        editingDraftId: [
            null as string | null,
            {
                setEditingDraft: (_, { draftId }) => draftId,
            },
        ],
        selectedSchema: [
            null as DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery | null,
            {
                selectSchema: (_, { schema }) => schema,
            },
        ],
        expandedFoldersByConnection: [
            {} as Record<string, string[]>,
            { persist: true },
            {
                setExpandedFolders: (state, { folderIds, connectionId }) => ({
                    ...state,
                    [getExpandedFoldersConnectionKey(connectionId ?? null)]: folderIds,
                }),
            },
        ],
        expandedSearchFolders: [
            [
                'sources',
                'views',
                'managed-views',
                'search-posthog',
                'search-system',
                'search-datawarehouse',
                'search-views',
                'search-managed-views',
            ] as string[],
            {
                setExpandedSearchFolders: (_, { folderIds }) => folderIds,
            },
        ],
        treeRef: [
            null as EditorSidebarTreeRef,
            {
                setTreeRef: (_, { ref }) => ref,
            },
        ],

        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
                clearSearch: () => '',
            },
        ],
        syncMoreNoticeDismissed: [
            false,
            { persist: true },
            {
                setSyncMoreNoticeDismissed: (_, { dismissed }) => dismissed,
            },
        ],
        pendingViewFolderOverrides: [
            {} as Record<string, string | null>,
            {
                setPendingViewFolderOverride: (state, { viewId, folderId }) => ({ ...state, [viewId]: folderId }),
                clearPendingViewFolderOverride: (state, { viewId }) => {
                    const nextState = { ...state }
                    delete nextState[viewId]
                    return nextState
                },
                clearPendingViewFolderOverrides: () => ({}),
            },
        ],
        activeDraggedViewId: [
            null as string | null,
            {
                startDraggingView: (_, { viewId }) => viewId,
                clearDraggedViewState: () => null,
            },
        ],
        highlightedDropFolderId: [
            null as string | null,
            {
                setDraggedViewDropState: (_, { folderId }) => folderId,
                clearDraggedViewState: () => null,
            },
        ],
        highlightViewsSectionDrop: [
            false,
            {
                setDraggedViewDropState: (_, { isViewsSectionDrop }) => isViewsSectionDrop,
                clearDraggedViewState: () => false,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        createDataWarehouseSavedQuerySuccess: ({ payload }) => {
            if (payload?.folder_id) {
                const folderNodeId = `view-folder-${payload.folder_id}`
                actions.setExpandedFolders(
                    Array.from(new Set([...values.expandedFolders, 'views', folderNodeId])),
                    values.connectionId
                )
            }
        },
        updateDraggedViewDropTarget: ({ dropTargetId }) => {
            const nextFolderId = getFolderIdFromDropTarget(values.displayedTreeData, dropTargetId)
            actions.setDraggedViewDropState(nextFolderId ?? null, nextFolderId === null)
        },
        moveDraggedViewToDropTarget: ({ viewId, dropTargetId }) => {
            const activeItem = findTreeItem(values.displayedTreeData, viewId)
            actions.clearDraggedViewState()

            if (activeItem?.record?.type !== 'view' || !activeItem.record.isSavedQuery) {
                return
            }

            const nextFolderId = getFolderIdFromDropTarget(values.displayedTreeData, dropTargetId)
            if (nextFolderId === undefined || activeItem.record.view.folder_id === nextFolderId) {
                return
            }

            actions.setPendingViewFolderOverride(activeItem.record.view.id, nextFolderId)
            actions.updateDataWarehouseSavedQuery({
                id: activeItem.record.view.id,
                folder_id: nextFolderId,
                soft_update: true,
            })
        },
        updateDataWarehouseSavedQuerySuccess: ({ payload }) => {
            if (payload?.id) {
                actions.clearPendingViewFolderOverride(payload.id)
            } else {
                actions.clearPendingViewFolderOverrides()
            }
        },
        updateDataWarehouseSavedQueryFailure: () => {
            actions.clearPendingViewFolderOverrides()
        },
    })),
    loaders(({ values }) => ({
        queryTabState: [
            null as QueryTabState | null,
            {
                loadQueryTabState: async () => {
                    if (!values.user) {
                        return null
                    }
                    try {
                        return await api.queryTabState.user(values.user?.uuid)
                    } catch (e) {
                        console.error(e)
                        return null
                    }
                },
                deleteUnsavedQuery: async ({ record }) => {
                    const { queryTabState } = values
                    if (!values.user || !queryTabState || !queryTabState.state || !queryTabState.id) {
                        return null
                    }
                    try {
                        const { editorModelsStateKey } = queryTabState.state
                        const queries = JSON.parse(editorModelsStateKey)
                        const newState = {
                            ...queryTabState,
                            state: {
                                ...queryTabState.state,
                                editorModelsStateKey: JSON.stringify(
                                    queries.filter((q: any) => q.name !== record.name && q.path !== record.path)
                                ),
                            },
                        }

                        await api.queryTabState.update(queryTabState.id, newState)

                        return newState
                    } catch (e) {
                        console.error(e)
                        return queryTabState
                    }
                },
            },
        ],
    })),
    selectors(({ actions }) => ({
        hasNonPosthogSources: [
            (s) => [s.dataWarehouseTables],
            (dataWarehouseTables: DatabaseSchemaDataWarehouseTable[]): boolean => {
                return dataWarehouseTables.length > 0
            },
        ],
        relevantPosthogTables: [
            (s) => [s.posthogTables, s.searchTerm],
            (
                posthogTables: DatabaseSchemaTable[],
                searchTerm: string
            ): [DatabaseSchemaTable, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return posthogTablesFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return posthogTables.map((table) => [table, null])
            },
        ],
        relevantSystemTables: [
            (s) => [s.systemTables, s.searchTerm],
            (
                systemTables: DatabaseSchemaTable[],
                searchTerm: string
            ): [DatabaseSchemaTable, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return systemTablesFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return systemTables.map((table) => [table, null])
            },
        ],
        relevantDataWarehouseTables: [
            (s) => [s.dataWarehouseTables, s.searchTerm],
            (
                dataWarehouseTables: DatabaseSchemaDataWarehouseTable[],
                searchTerm: string
            ): [DatabaseSchemaDataWarehouseTable, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return dataWarehouseTablesFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return dataWarehouseTables.map((table) => [table, null])
            },
        ],
        relevantSavedQueries: [
            (s) => [s.effectiveDataWarehouseSavedQueries, s.searchTerm],
            (
                dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
                searchTerm: string
            ): [DataWarehouseSavedQuery, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return savedQueriesFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return (dataWarehouseSavedQueries ?? []).map((query) => [query, null])
            },
        ],
        relevantSavedQueryFolders: [
            (s) => [s.dataWarehouseSavedQueryFolders, s.searchTerm],
            (
                dataWarehouseSavedQueryFolders: DataWarehouseSavedQueryFolder[],
                searchTerm: string
            ): [DataWarehouseSavedQueryFolder, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return savedQueryFoldersFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return (dataWarehouseSavedQueryFolders ?? []).map((folder) => [folder, null])
            },
        ],
        effectiveDataWarehouseSavedQueries: [
            (s) => [s.dataWarehouseSavedQueries, s.pendingViewFolderOverrides],
            (
                dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
                pendingViewFolderOverrides: Record<string, string | null>
            ): DataWarehouseSavedQuery[] =>
                (dataWarehouseSavedQueries ?? []).map((savedQuery) =>
                    Object.prototype.hasOwnProperty.call(pendingViewFolderOverrides, savedQuery.id)
                        ? {
                              ...savedQuery,
                              folder_id: pendingViewFolderOverrides[savedQuery.id],
                          }
                        : savedQuery
                ),
        ],
        relevantManagedViews: [
            (s) => [s.managedViews, s.searchTerm],
            (
                managedViews: DatabaseSchemaManagedViewTable[],
                searchTerm: string
            ): [DatabaseSchemaManagedViewTable, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return managedViewsFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return managedViews.map((view) => [view, null])
            },
        ],
        relevantDrafts: [
            (s) => [s.drafts, s.searchTerm],
            (
                drafts: DataWarehouseSavedQueryDraft[],
                searchTerm: string
            ): [DataWarehouseSavedQueryDraft, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return draftsFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return drafts.map((draft) => [draft, null])
            },
        ],
        relevantEndpointTables: [
            (s) => [s.latestEndpointTables, s.searchTerm],
            (
                latestEndpointTables: DatabaseSchemaEndpointTable[],
                searchTerm: string
            ): [DatabaseSchemaEndpointTable, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return endpointsFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return latestEndpointTables.map((table) => [table, null])
            },
        ],
        selectedDirectSource: [
            (s) => [s.dataWarehouseSources, s.connectionId],
            (dataWarehouseSources, connectionId): { job_inputs?: Record<string, any> } | undefined => {
                return dataWarehouseSources?.results.find((source) => source.id === connectionId)
            },
        ],
        searchTreeSourceContext: [
            (s) => [
                s.allPosthogTables,
                s.systemTables,
                s.dataWarehouseTables,
                s.effectiveDataWarehouseSavedQueries,
                s.dataWarehouseSavedQueryFolders,
                s.managedViews,
                s.allTablesMap,
            ],
            (
                allPosthogTables: DatabaseSchemaTable[],
                systemTables: DatabaseSchemaTable[],
                dataWarehouseTables: DatabaseSchemaDataWarehouseTable[],
                dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
                dataWarehouseSavedQueryFolders: DataWarehouseSavedQueryFolder[],
                managedViews: DatabaseSchemaManagedViewTable[],
                allTablesMap: Record<string, DatabaseSchemaTable>
            ): SearchTreeSourceContext => ({
                allPosthogTables,
                systemTables,
                dataWarehouseTables,
                dataWarehouseSavedQueries,
                dataWarehouseSavedQueryFolders,
                managedViews,
                allTablesMap,
            }),
        ],
        searchTreeMatches: [
            (s) => [
                s.relevantPosthogTables,
                s.relevantSystemTables,
                s.relevantDataWarehouseTables,
                s.relevantSavedQueries,
                s.relevantSavedQueryFolders,
                s.relevantManagedViews,
                s.relevantDrafts,
                s.relevantEndpointTables,
            ],
            (
                relevantPosthogTables: [DatabaseSchemaTable, FuseSearchMatch[] | null][],
                relevantSystemTables: [DatabaseSchemaTable, FuseSearchMatch[] | null][],
                relevantDataWarehouseTables: [DatabaseSchemaDataWarehouseTable, FuseSearchMatch[] | null][],
                relevantSavedQueries: [DataWarehouseSavedQuery, FuseSearchMatch[] | null][],
                relevantSavedQueryFolders: [DataWarehouseSavedQueryFolder, FuseSearchMatch[] | null][],
                relevantManagedViews: [DatabaseSchemaManagedViewTable, FuseSearchMatch[] | null][],
                relevantDrafts: [DataWarehouseSavedQueryDraft, FuseSearchMatch[] | null][],
                relevantEndpointTables: [DatabaseSchemaEndpointTable, FuseSearchMatch[] | null][]
            ): SearchTreeMatches => ({
                relevantPosthogTables,
                relevantSystemTables,
                relevantDataWarehouseTables,
                relevantSavedQueries,
                relevantSavedQueryFolders,
                relevantManagedViews,
                relevantDrafts,
                relevantEndpointTables,
            }),
        ],
        searchTreeData: [
            (s) => [
                s.searchTreeSourceContext,
                s.searchTreeMatches,
                s.searchTerm,
                s.featureFlags,
                s.expandedSearchFolders,
            ],
            (
                searchTreeSourceContext: SearchTreeSourceContext,
                searchTreeMatches: SearchTreeMatches,
                searchTerm: string,
                featureFlags: FeatureFlagsSet,
                expandedSearchFolders: string[]
            ): TreeDataItem[] => {
                if (!searchTerm) {
                    return []
                }

                const {
                    allPosthogTables,
                    systemTables,
                    dataWarehouseTables,
                    dataWarehouseSavedQueries,
                    dataWarehouseSavedQueryFolders,
                    managedViews,
                    allTablesMap,
                } = searchTreeSourceContext
                const {
                    relevantPosthogTables,
                    relevantSystemTables,
                    relevantDataWarehouseTables,
                    relevantSavedQueries,
                    relevantSavedQueryFolders,
                    relevantManagedViews,
                    relevantDrafts,
                    relevantEndpointTables,
                } = searchTreeMatches

                const tableLookup = createTableLookup({
                    posthogTables: allPosthogTables,
                    systemTables,
                    dataWarehouseTables,
                    dataWarehouseSavedQueries,
                    managedViews,
                    savedQuerySchemaTables: allTablesMap,
                })
                const expandedLazyNodeIds = new Set(expandedSearchFolders.filter(isLazyNodeId))
                const sourcesChildren: TreeDataItem[] = []
                const expandedIds: string[] = []
                const tableNodeOptions = { expandedLazyNodeIds }

                // Add PostHog tables
                if (relevantPosthogTables.length > 0) {
                    expandedIds.push('search-posthog')
                    sourcesChildren.push(
                        createSourceFolderNode(
                            'PostHog',
                            [],
                            relevantPosthogTables,
                            true,
                            tableLookup,
                            tableNodeOptions
                        )
                    )
                }

                // Add System tables
                if (relevantSystemTables.length > 0) {
                    expandedIds.push('search-system')
                    sourcesChildren.push(
                        createSourceFolderNode('System', [], relevantSystemTables, true, tableLookup, tableNodeOptions)
                    )
                }

                // Group data warehouse tables by source type
                const tablesBySourceType = relevantDataWarehouseTables.reduce(
                    (
                        acc: Record<string, [DatabaseSchemaDataWarehouseTable, FuseSearchMatch[] | null][]>,
                        [table, matches]
                    ) => {
                        const sourceType = table.source?.source_type || 'Self-managed'
                        if (!acc[sourceType]) {
                            acc[sourceType] = []
                        }
                        acc[sourceType].push([table, matches])
                        return acc
                    },
                    {}
                )

                Object.entries(tablesBySourceType).forEach(([sourceType, tablesWithMatches]) => {
                    expandedIds.push(`search-${sourceType}`)
                    sourcesChildren.push(
                        createSourceFolderNode(sourceType, [], tablesWithMatches, true, tableLookup, tableNodeOptions)
                    )
                })

                // Create views children
                const viewsChildren: TreeDataItem[] = []
                const managedViewsChildren: TreeDataItem[] = []
                const draftsChildren: TreeDataItem[] = []
                const matchedFolderMap = new Map<
                    string,
                    { folder: DataWarehouseSavedQueryFolder; matches: FuseSearchMatch[] | null }
                >()
                const viewChildrenByFolderId = new Map<string, TreeDataItem[]>()

                relevantSavedQueryFolders.forEach(([folder, matches]) => {
                    matchedFolderMap.set(folder.id, { folder, matches })
                })

                // Add saved queries
                relevantSavedQueries.forEach(([view, matches]) => {
                    const schemaTable = getSavedQuerySchemaTable(view, allTablesMap)
                    const viewNode = createViewNode(view, matches, true, tableLookup, tableNodeOptions, schemaTable)
                    if (view.folder_id) {
                        const currentChildren = viewChildrenByFolderId.get(view.folder_id) ?? []
                        currentChildren.push(viewNode)
                        viewChildrenByFolderId.set(view.folder_id, currentChildren)
                    } else {
                        viewsChildren.push(viewNode)
                    }
                })

                dataWarehouseSavedQueryFolders.forEach((folder) => {
                    const folderChildren = viewChildrenByFolderId.get(folder.id) ?? []
                    const folderMatch = matchedFolderMap.get(folder.id)?.matches ?? null
                    if (folderChildren.length > 0 || folderMatch) {
                        expandedIds.push(`search-view-folder-${folder.id}`)
                        viewsChildren.push(createViewFolderNode(folder, folderChildren, folderMatch, true))
                    }
                })

                // Add endpoint tables
                relevantEndpointTables.forEach(([endpointTable, matches]) => {
                    viewsChildren.push(createEndpointNode(endpointTable, matches, true, tableLookup, tableNodeOptions))
                })

                // Add managed views
                relevantManagedViews.forEach(([view, matches]) => {
                    managedViewsChildren.push(createManagedViewNode(view, matches, true, tableLookup, tableNodeOptions))
                })

                // Add drafts
                if (featureFlags[FEATURE_FLAGS.EDITOR_DRAFTS]) {
                    relevantDrafts.forEach(([draft, matches]) => {
                        draftsChildren.push(createDraftNode(draft, matches, true))
                    })
                }

                const searchResults: TreeDataItem[] = []

                if (sourcesChildren.length > 0) {
                    expandedIds.push('search-sources')
                    searchResults.push(createTopLevelFolderNode('sources', sourcesChildren, true, <IconPlug />))
                }

                if (viewsChildren.length > 0) {
                    expandedIds.push('search-views')
                    searchResults.push(createTopLevelFolderNode('views', viewsChildren, true))
                }

                if (managedViewsChildren.length > 0 && !featureFlags[FEATURE_FLAGS.MANAGED_VIEWSETS]) {
                    expandedIds.push('search-managed-views')
                    searchResults.push(createTopLevelFolderNode('managed-views', managedViewsChildren, true))
                }

                // TODO: this needs to moved to the backend
                if (draftsChildren.length > 0) {
                    expandedIds.push('search-drafts')
                    searchResults.push(createTopLevelFolderNode('drafts', draftsChildren, true))
                }

                const expandedIdSet = new Set(expandedSearchFolders)
                const missingRequiredExpansion = expandedIds.some((id) => !expandedIdSet.has(id))

                if (missingRequiredExpansion) {
                    // Auto-expand only parent folders, not the matching nodes themselves.
                    setTimeout(() => {
                        actions.setExpandedSearchFolders(
                            Array.from(new Set([...expandedSearchFolders, ...expandedIds]))
                        )
                    }, 0)
                }

                return searchResults
            },
        ],
        treeDataContext: [
            (s) => [
                s.allPosthogTables,
                s.posthogTables,
                s.systemTables,
                s.dataWarehouseTables,
                s.effectiveDataWarehouseSavedQueries,
                s.dataWarehouseSavedQueryFolders,
                s.managedViews,
                s.latestEndpointTables,
                s.allTablesMap,
            ],
            (
                allPosthogTables: DatabaseSchemaTable[],
                posthogTables: DatabaseSchemaTable[],
                systemTables: DatabaseSchemaTable[],
                dataWarehouseTables: DatabaseSchemaDataWarehouseTable[],
                dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
                dataWarehouseSavedQueryFolders: DataWarehouseSavedQueryFolder[],
                managedViews: DatabaseSchemaManagedViewTable[],
                latestEndpointTables: DatabaseSchemaEndpointTable[],
                allTablesMap: Record<string, DatabaseSchemaTable>
            ): TreeDataContext => ({
                allPosthogTables,
                posthogTables,
                systemTables,
                dataWarehouseTables,
                dataWarehouseSavedQueries,
                dataWarehouseSavedQueryFolders,
                managedViews,
                latestEndpointTables,
                allTablesMap,
            }),
        ],
        treeData: [
            (s) => [
                s.treeDataContext,
                s.databaseLoading,
                s.dataWarehouseSavedQueriesLoading,
                s.drafts,
                s.draftsResponseLoading,
                s.hasMoreDrafts,
                s.featureFlags,
                s.queryTabState,
                s.expandedFolders,
            ],
            (
                treeDataContext: TreeDataContext,
                databaseLoading: boolean,
                dataWarehouseSavedQueriesLoading: boolean,
                drafts: DataWarehouseSavedQueryDraft[],
                draftsResponseLoading: boolean,
                hasMoreDrafts: boolean,
                featureFlags: FeatureFlagsSet,
                queryTabState: QueryTabState | null,
                expandedFolders: string[]
            ): TreeDataItem[] => {
                const {
                    allPosthogTables,
                    posthogTables,
                    systemTables,
                    dataWarehouseTables,
                    dataWarehouseSavedQueries,
                    dataWarehouseSavedQueryFolders,
                    managedViews,
                    latestEndpointTables,
                    allTablesMap,
                } = treeDataContext
                const sourcesChildren: TreeDataItem[] = []
                const tableLookup = createTableLookup({
                    posthogTables: allPosthogTables,
                    systemTables,
                    dataWarehouseTables,
                    dataWarehouseSavedQueries,
                    managedViews,
                    savedQuerySchemaTables: allTablesMap,
                })
                const expandedLazyNodeIds = new Set(expandedFolders.filter(isLazyNodeId))
                const tableNodeOptions = { expandedLazyNodeIds }

                // Add loading indicator for sources if still loading
                if (databaseLoading && posthogTables.length === 0 && dataWarehouseTables.length === 0) {
                    sourcesChildren.push({
                        id: 'sources-loading/',
                        name: 'Loading...',
                        displayName: <>Loading...</>,
                        icon: <Spinner />,
                        disableSelect: true,
                        type: 'loading-indicator',
                    })
                } else {
                    // Add PostHog tables
                    if (posthogTables.length > 0) {
                        sourcesChildren.push(
                            createSourceFolderNode('PostHog', posthogTables, [], false, tableLookup, tableNodeOptions)
                        )
                    }

                    // Add System tables
                    if (systemTables.length > 0) {
                        systemTables.sort((a, b) => a.name.localeCompare(b.name))
                        sourcesChildren.push(
                            createSourceFolderNode('System', systemTables, [], false, tableLookup, tableNodeOptions)
                        )
                    }

                    // Group data warehouse tables by source type
                    const tablesBySourceType = dataWarehouseTables.reduce(
                        (acc: Record<string, DatabaseSchemaDataWarehouseTable[]>, table) => {
                            const sourceType = table.source?.source_type || 'Self-managed'
                            if (!acc[sourceType]) {
                                acc[sourceType] = []
                            }
                            acc[sourceType].push(table)
                            return acc
                        },
                        {}
                    )

                    // Add data warehouse tables
                    Object.entries(tablesBySourceType).forEach(([sourceType, tables]) => {
                        sourcesChildren.push(
                            createSourceFolderNode(sourceType, tables, [], false, tableLookup, tableNodeOptions)
                        )
                    })
                }

                // Create views children
                const viewsChildren: TreeDataItem[] = []
                const managedViewsChildren: TreeDataItem[] = []

                // Add loading indicator for views if still loading
                if (
                    dataWarehouseSavedQueriesLoading &&
                    dataWarehouseSavedQueries.length === 0 &&
                    managedViews.length === 0
                ) {
                    viewsChildren.push({
                        id: 'views-loading/',
                        name: 'Loading...',
                        displayName: <>Loading...</>,
                        icon: <Spinner />,
                        disableSelect: true,
                        type: 'loading-indicator',
                    })

                    managedViewsChildren.push({
                        id: 'managed-views-loading/',
                        name: 'Loading...',
                        displayName: <>Loading...</>,
                        icon: <Spinner />,
                        disableSelect: true,
                        type: 'loading-indicator',
                    })
                } else {
                    const viewChildrenByFolderId = new Map<string, TreeDataItem[]>()

                    // Add saved queries
                    dataWarehouseSavedQueries.forEach((view) => {
                        const schemaTable = getSavedQuerySchemaTable(view, allTablesMap)
                        const viewNode = createViewNode(view, null, false, tableLookup, tableNodeOptions, schemaTable)
                        if (view.folder_id) {
                            const folderChildren = viewChildrenByFolderId.get(view.folder_id) ?? []
                            folderChildren.push(viewNode)
                            viewChildrenByFolderId.set(view.folder_id, folderChildren)
                        } else {
                            viewsChildren.push(viewNode)
                        }
                    })

                    dataWarehouseSavedQueryFolders.forEach((folder) => {
                        const folderChildren = viewChildrenByFolderId.get(folder.id) ?? []
                        folderChildren.sort((a, b) => a.name.localeCompare(b.name))
                        viewsChildren.push(createViewFolderNode(folder, folderChildren))
                    })

                    // Add latest endpoint tables
                    latestEndpointTables.forEach((endpointTable) => {
                        viewsChildren.push(
                            createEndpointNode(endpointTable, null, false, tableLookup, tableNodeOptions)
                        )
                    })

                    // Add managed views
                    managedViews.forEach((view) => {
                        managedViewsChildren.push(
                            createManagedViewNode(view, null, false, tableLookup, tableNodeOptions)
                        )
                    })
                }

                viewsChildren.sort((a, b) => a.name.localeCompare(b.name))
                managedViewsChildren.sort((a, b) => a.name.localeCompare(b.name))

                const states = queryTabState?.state?.editorModelsStateKey
                const unsavedChildren: TreeDataItem[] = []
                let i = 1
                if (states) {
                    try {
                        for (const state of JSON.parse(states)) {
                            unsavedChildren.push({
                                id: `unsaved-${i++}`,
                                name: state.name || 'Unsaved query',
                                type: 'node',
                                icon: <IconDocument />,
                                record: { type: 'unsaved-query', ...state },
                            })
                        }
                    } catch {
                        // do nothing
                    }
                }

                const draftsChildren: TreeDataItem[] = []

                if (featureFlags[FEATURE_FLAGS.EDITOR_DRAFTS]) {
                    if (draftsResponseLoading && drafts.length === 0) {
                        draftsChildren.push({
                            id: 'drafts-loading/',
                            name: 'Loading...',
                            displayName: <>Loading...</>,
                            icon: <Spinner />,
                            disableSelect: true,
                            type: 'loading-indicator',
                        })
                    } else {
                        drafts.forEach((draft) => {
                            draftsChildren.push(createDraftNode(draft))
                        })

                        if (drafts.length > 0 && draftsResponseLoading) {
                            draftsChildren.push({
                                id: 'drafts-loading/',
                                name: 'Loading...',
                                displayName: <>Loading...</>,
                                icon: <Spinner />,
                                disableSelect: true,
                                type: 'loading-indicator',
                            })
                        } else if (hasMoreDrafts) {
                            draftsChildren.push({
                                id: 'drafts-load-more/',
                                name: 'Load more...',
                                displayName: <>Load more...</>,
                                icon: <IconPlus />,
                                onClick: () => {
                                    actions.loadMoreDrafts()
                                },
                            })
                        }
                    }
                }

                return [
                    createTopLevelFolderNode('sources', sourcesChildren, false, <IconPlug />),
                    ...(featureFlags[FEATURE_FLAGS.EDITOR_DRAFTS]
                        ? [createTopLevelFolderNode('drafts', draftsChildren, false)]
                        : []),
                    ...(unsavedChildren.length > 0
                        ? [
                              {
                                  id: 'unsaved-folder',
                                  name: 'Unsaved queries',
                                  type: 'node',
                                  icon: <IconDocument />,
                                  record: {
                                      type: 'unsaved-folder',
                                  },
                                  children: unsavedChildren,
                              } as TreeDataItem,
                          ]
                        : []),
                    createTopLevelFolderNode('views', viewsChildren),
                    ...(featureFlags[FEATURE_FLAGS.MANAGED_VIEWSETS]
                        ? []
                        : [createTopLevelFolderNode('managed-views', managedViewsChildren)]),
                ]
            },
        ],
        displayedTreeData: [
            (s) => [s.searchTerm, s.searchTreeData, s.treeData, s.connectionId, s.selectedDirectSource],
            (
                searchTerm: string,
                searchTreeData: TreeDataItem[],
                treeData: TreeDataItem[],
                connectionId: string | null,
                selectedDirectSource: { job_inputs?: Record<string, any> } | undefined
            ): TreeDataItem[] => {
                const sourceData = searchTerm ? searchTreeData : treeData

                if (!shouldUseDirectConnectionTree(connectionId)) {
                    return sourceData
                }

                const flattenedTables: TreeDataItem[] = []
                const flattenedViews: TreeDataItem[] = []
                const additionalItems: TreeDataItem[] = []
                const defaultSchemaName =
                    typeof selectedDirectSource?.job_inputs?.schema === 'string'
                        ? selectedDirectSource.job_inputs.schema
                        : null

                sourceData.forEach((item) => {
                    if (item.record?.type === 'sources') {
                        const sourceChildren = item.children ?? []
                        sourceChildren.forEach((sourceChild) => {
                            if (sourceChild.record?.type === 'source-folder') {
                                flattenedTables.push(...(sourceChild.children ?? []))
                                return
                            }

                            flattenedTables.push(sourceChild)
                        })
                        return
                    }

                    if (item.record?.type === 'views') {
                        // In direct-connection mode, hide saved-query and managed view sections,
                        // and only keep DB-backed view nodes if they are present in schema.
                        flattenViewNodes(item.children ?? [], flattenedViews)
                        return
                    }

                    if (item.record?.type === 'managed-views') {
                        return
                    }

                    additionalItems.push(item)
                })

                return [
                    ...groupDirectConnectionTableNodesBySchema(flattenedTables, !!searchTerm, defaultSchemaName),
                    ...(flattenedViews.length > 0
                        ? [
                              {
                                  id: searchTerm ? 'search-views' : 'views',
                                  name: 'Views',
                                  type: 'node' as const,
                                  icon: <IconDatabase />,
                                  record: { type: 'views' },
                                  children: flattenedViews,
                              },
                          ]
                        : []),
                    ...additionalItems,
                ]
            },
        ],
        activeExpandedFolderIds: [
            (s) => [s.searchTerm, s.expandedSearchFolders, s.expandedFolders],
            (searchTerm: string, expandedSearchFolders: string[], expandedFolders: string[]): string[] => {
                return searchTerm ? expandedSearchFolders : expandedFolders
            },
        ],
        expandedFolders: [
            (s) => [s.connectionId, s.expandedFoldersByConnection],
            (connectionId: string | null, expandedFoldersByConnection: Record<string, string[]>): string[] => {
                const key = getExpandedFoldersConnectionKey(connectionId)

                return Object.prototype.hasOwnProperty.call(expandedFoldersByConnection, key)
                    ? expandedFoldersByConnection[key]
                    : [...DEFAULT_EXPANDED_FOLDERS]
            },
        ],
        defaultExpandedRootIds: [
            (s) => [s.connectionId, s.displayedTreeData],
            (connectionId: string | null, displayedTreeData: TreeDataItem[]): string[] =>
                getDefaultExpandedRootIds(connectionId, displayedTreeData),
        ],
        expandedItemIds: [
            (s) => [s.activeExpandedFolderIds, s.defaultExpandedRootIds],
            (activeExpandedFolderIds: string[], defaultExpandedRootIds: string[]): string[] => {
                return Array.from(new Set([...defaultExpandedRootIds, ...activeExpandedFolderIds]))
            },
        ],
        joinsByFieldName: [
            (s) => [s.joins],
            (joins: DataWarehouseViewLink[]): Record<string, DataWarehouseViewLink> => {
                return joins.reduce(
                    (acc, join) => {
                        if (join.field_name && join.source_table_name) {
                            acc[`${join.source_table_name}.${join.field_name}`] = join
                        }
                        return acc
                    },
                    {} as Record<string, DataWarehouseViewLink>
                )
            },
        ],
        sidebarOverlayTreeItems: [
            (s) => [
                s.selectedSchema,
                s.posthogTablesMap,
                s.systemTablesMap,
                s.dataWarehouseTablesMap,
                s.dataWarehouseSavedQueryMapById,
                s.viewsMapById,
                s.joinsByFieldName,
            ],
            (
                selectedSchema,
                posthogTablesMap,
                systemTablesMap,
                dataWarehouseTablesMap,
                dataWarehouseSavedQueryMapById,
                viewsMapById,
                joinsByFieldName
            ): TreeItem[] => {
                if (selectedSchema === null) {
                    return []
                }
                let table: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery | null =
                    null
                if (isPostHogTable(selectedSchema)) {
                    table = posthogTablesMap[selectedSchema.name]
                } else if (isSystemTable(selectedSchema)) {
                    table = systemTablesMap[selectedSchema.name]
                } else if (isDataWarehouseTable(selectedSchema)) {
                    table = dataWarehouseTablesMap[selectedSchema.name]
                } else if (isManagedViewTable(selectedSchema)) {
                    table = viewsMapById[selectedSchema.id]
                } else if (isViewTable(selectedSchema)) {
                    table = dataWarehouseSavedQueryMapById[selectedSchema.id]
                }

                if (table == null) {
                    return []
                }

                const menuItems = (field: DatabaseSchemaField, tableName: string): LemonMenuItem[] => {
                    return isJoined(field) && joinsByFieldName[`${tableName}.${field.name}`]
                        ? [
                              {
                                  label: 'Edit',
                                  onClick: () => {
                                      actions.toggleEditJoinModal(joinsByFieldName[`${tableName}.${field.name}`])
                                  },
                              },
                              {
                                  label: 'Delete join',
                                  status: 'danger',
                                  onClick: () => {
                                      const join = joinsByFieldName[`${tableName}.${field.name}`]
                                      actions.deleteJoin(join)
                                  },
                              },
                          ]
                        : []
                }

                if ('fields' in table && table !== null) {
                    return sortFieldsWithPrimary(table.name, Object.values(table.fields))
                        .filter((field) => !shouldHideField(field))
                        .map((field) => ({
                            name: field.name,
                            type: field.type,
                            menuItems: menuItems(field, table?.name ?? ''), // table cant be null, but the typechecker is confused
                        }))
                }

                if ('columns' in table && table !== null) {
                    return sortFieldsWithPrimary(table.name, Object.values(table.columns))
                        .filter((column) => !shouldHideField(column))
                        .map((column) => ({
                            name: column.name,
                            type: column.type,
                            menuItems: menuItems(column, table?.name ?? ''), // table cant be null, but the typechecker is confused
                        }))
                }
                return []
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        toggleFolderOpen: ({ folderId, isExpanded }) => {
            const expandedFolders = values.searchTerm ? values.expandedSearchFolders : values.expandedFolders

            if (isExpanded) {
                if (values.searchTerm) {
                    actions.setExpandedSearchFolders(expandedFolders.filter((f) => f !== folderId))
                } else {
                    actions.setExpandedFolders(
                        expandedFolders.filter((f) => f !== folderId),
                        values.connectionId
                    )
                }
            } else {
                if (values.searchTerm) {
                    actions.setExpandedSearchFolders([...expandedFolders, folderId])
                } else {
                    actions.setExpandedFolders([...expandedFolders, folderId], values.connectionId)
                }
            }
        },
        selectSourceTable: ({ tableName }) => {
            // Connect to viewLinkLogic actions
            viewLinkLogic.actions.selectSourceTable(tableName)
            viewLinkLogic.actions.toggleJoinTableModal()
        },
        openUnsavedQuery: ({ record }) => {
            if (record.insight) {
                sceneLogic.actions.newTab(urls.sqlEditor({ insightShortId: record.insight.short_id }))
            } else if (record.view) {
                sceneLogic.actions.newTab(urls.sqlEditor({ view_id: record.view.id }))
            } else {
                sceneLogic.actions.newTab(urls.sqlEditor({ query: record.query }))
            }
        },
    })),
    subscriptions(({ actions, values }) => ({
        displayedTreeData: (displayedTreeData: TreeDataItem[]) => {
            if (values.searchTerm || !shouldUseDirectConnectionTree(values.connectionId)) {
                return
            }

            const key = getExpandedFoldersConnectionKey(values.connectionId)
            const currentExpandedFolders = values.expandedFoldersByConnection[key]

            if (!shouldInitializeDirectConnectionExpandedFolders(displayedTreeData, currentExpandedFolders)) {
                return
            }

            actions.setExpandedFolders(
                getInitialExpandedFolders(values.connectionId, displayedTreeData),
                values.connectionId
            )
        },
        posthogTables: (posthogTables: DatabaseSchemaTable[]) => {
            posthogTablesFuse.setCollection(posthogTables)
        },
        systemTables: (systemTables: DatabaseSchemaTable[]) => {
            systemTablesFuse.setCollection(systemTables)
        },
        dataWarehouseTables: (dataWarehouseTables: DatabaseSchemaDataWarehouseTable[]) => {
            dataWarehouseTablesFuse.setCollection(dataWarehouseTables)
        },
        dataWarehouseSavedQueries: (dataWarehouseSavedQueries: DataWarehouseSavedQuery[]) => {
            savedQueriesFuse.setCollection(dataWarehouseSavedQueries)
        },
        dataWarehouseSavedQueryFolders: (dataWarehouseSavedQueryFolders: DataWarehouseSavedQueryFolder[]) => {
            savedQueryFoldersFuse.setCollection(dataWarehouseSavedQueryFolders)
        },
        managedViews: (managedViews: DatabaseSchemaManagedViewTable[]) => {
            managedViewsFuse.setCollection(managedViews)
        },
        drafts: (drafts: DataWarehouseSavedQueryDraft[]) => {
            draftsFuse.setCollection(drafts)
        },
        latestEndpointTables: (latestEndpointTables: DatabaseSchemaEndpointTable[]) => {
            endpointsFuse.setCollection(latestEndpointTables)
        },
    })),
    events(({ actions, values }) => ({
        afterMount: () => {
            if (values.featureFlags[FEATURE_FLAGS.EDITOR_DRAFTS]) {
                actions.loadDrafts()
            }
            actions.loadQueryTabState()
        },
    })),
])
