import { MakeLogicType, actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import {
    IconBolt,
    IconBrackets,
    IconDatabase,
    IconDocument,
    IconEndpoints,
    IconFolder,
    IconPlug,
    IconPlus,
    IconRefresh,
    IconWarning,
} from '@posthog/icons'
import { LemonMenuItem } from '@posthog/lemon-ui'
import { Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { TreeItem } from 'lib/components/DatabaseTableTree/DatabaseTableTree'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTreeRef, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils/dom'
import { createFuse, IFuseOptions } from 'lib/utils/fuseSearch'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { TableFieldsStatus, databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { POSTHOG_WAREHOUSE } from 'scenes/data-warehouse/editor/connectionSelectorLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { propertyDefinitionsList } from '~/generated/core/api'
import type { EnterprisePropertyDefinitionApi, PropertyDefinitionsListType } from '~/generated/core/api.schemas'
import {
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaEndpointTable,
    DatabaseSchemaField,
    DatabaseSchemaManagedViewTable,
    DatabaseSchemaTable,
} from '~/queries/schema/schema-general'
import { escapeDottedHogQLIdentifier, escapeRawPropertyAsHogQLIdentifier } from '~/queries/utils'
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

import type { PaginatedResponse } from '../../../../lib/api'
import type { DatabaseSchemaViewTable } from '../../../../queries/schema/schema-general'
import type { ExternalDataSource, UserType } from '../../../../types'
import { dataWarehouseViewsLogic } from '../../saved_queries/dataWarehouseViewsLogic'
import { viewLinkLogic } from '../../viewLinkLogic'
import { draftsLogic } from '../draftsLogic'

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
    keys: [
        { name: 'name', weight: 2 },
        // Warehouse tables are queryable by alternate names (e.g. the flat underscore form) too
        { name: 'search_aliases', weight: 1 },
    ],
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
    propertyDefinitionLists?: Record<string, SidebarPropertyDefinitionList>
    loadPropertyDefinitions?: (
        propertyFieldKey: string,
        target: SidebarPropertyDefinitionTarget,
        offset: number
    ) => void
    allowPropertyDefinitionExpansion?: boolean
    visitedColumnPaths?: Set<string>
    depth?: number
    hydration?: TableFieldsHydration
}

// With a shallow (lazy) schema load, tables arrive without fields; this tracks which tables'
// fields the store actually holds so the tree can show spinners and request the missing ones.
type TableFieldsHydration = {
    databaseFieldsComplete: boolean
    tableFieldsStatus: TableFieldsStatus
}

type TableFieldsState = 'ready' | 'pending' | 'error'

const getTableFieldsState = (
    tableName: string,
    fields: Record<string, DatabaseSchemaField> | undefined,
    hydration?: TableFieldsHydration
): TableFieldsState => {
    const status = hydration?.tableFieldsStatus[tableName]
    if (status === 'error') {
        return 'error'
    }
    if (!hydration || hydration.databaseFieldsComplete) {
        return 'ready'
    }
    if (fields && Object.keys(fields).length > 0) {
        return 'ready'
    }
    if (status === 'loaded') {
        // Hydrated and the table genuinely has no fields.
        return 'ready'
    }
    return 'pending'
}

export type SidebarPropertyDefinitionTarget = {
    type: PropertyDefinitionsListType
    groupTypeIndex?: number
}

export type SidebarPropertyDefinitionList = {
    activeRequestId: string | null
    count: number
    definitions: EnterprisePropertyDefinitionApi[]
    error: boolean
    loading: boolean
    search: string
}

const PROPERTY_DEFINITIONS_PAGE_SIZE = 25

export const getSidebarPropertyDefinitionTarget = (
    tableName: string,
    columnPath: string,
    field: DatabaseSchemaField
): SidebarPropertyDefinitionTarget | null => {
    if (field.type !== 'json') {
        return null
    }

    const pathSegments = columnPath.split('.')
    const fieldName = pathSegments.at(-1)
    if (fieldName !== 'properties' && fieldName !== 'person_properties') {
        return null
    }

    if (fieldName === 'person_properties') {
        return { type: 'person' }
    }

    const groupPathSegment = pathSegments.find((segment) => /^(?:group|goe)_[0-4]$/.test(segment))
    if (groupPathSegment) {
        return { type: 'group', groupTypeIndex: Number(groupPathSegment.at(-1)) }
    }

    if (
        ['persons', 'raw_persons'].includes(tableName) ||
        pathSegments.some((segment) => ['person', 'pdi', 'poe'].includes(segment))
    ) {
        return { type: 'person' }
    }

    if (['ai_events', 'events'].includes(tableName) && columnPath === 'properties') {
        return { type: 'event' }
    }

    return null
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

const findTreeItemById = (nodes: TreeDataItem[], id: string): TreeDataItem | null => {
    for (const node of nodes) {
        if (node.id === id) {
            return node
        }
        if (node.children) {
            const found = findTreeItemById(node.children, id)
            if (found) {
                return found
            }
        }
    }
    return null
}

// Which table's fields a tree node needs once expanded: the table itself, or for join/traverser
// nodes the joined table on the other side.
const getHydrationTableNamesForNode = (node: TreeDataItem): string[] => {
    const record = node.record as Record<string, any> | undefined
    if (!record) {
        return []
    }
    if ((record.type === 'table' || record.type === 'endpoint') && record.table?.name) {
        return [record.table.name]
    }
    if ((record.type === 'lazy-table' || record.type === 'field-traverser') && record.referencedTable) {
        const name = normalizeTableLookupKey(record.referencedTable)
        return name ? [name] : []
    }
    if (record.type === 'managed-view' && record.view?.name) {
        return [record.view.name]
    }
    return []
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

const shouldUseDirectConnectionTree = (connectionId: string | null): connectionId is string => {
    return !!connectionId && connectionId !== POSTHOG_WAREHOUSE
}

const createColumnNode = (
    tableName: string,
    field: DatabaseSchemaField,
    columnPath: string,
    isSearch = false,
    hogqlExpression?: string
): TreeDataItem => ({
    id: `${isSearch ? 'search-' : ''}col-${tableName}-${columnPath}`,
    name: field.name,
    type: 'node',
    record: {
        type: 'column',
        columnName: columnPath,
        field,
        hogqlExpression,
        table: tableName,
    },
})

const getPropertyDefinitionFieldType = (
    propertyDefinition: EnterprisePropertyDefinitionApi
): DatabaseSchemaField['type'] => {
    switch (propertyDefinition.property_type) {
        case 'Boolean':
            return 'boolean'
        case 'DateTime':
            return 'datetime'
        case 'Duration':
        case 'Numeric':
            return 'float'
        default:
            return 'string'
    }
}

const createPropertyDefinitionChildren = (
    tableName: string,
    columnPath: string,
    isSearch: boolean,
    propertyFieldKey: string,
    target: SidebarPropertyDefinitionTarget,
    propertyDefinitionList: SidebarPropertyDefinitionList | undefined,
    loadPropertyDefinitions: FieldTraversalOptions['loadPropertyDefinitions']
): TreeDataItem[] => {
    if (!propertyDefinitionList) {
        return [
            {
                id: `${isSearch ? 'search-' : ''}property-${tableName}-${columnPath}-placeholder/`,
                name: 'Loading...',
                displayName: <>Loading...</>,
                icon: <Spinner />,
                disableSelect: true,
                type: 'loading-indicator',
            },
        ]
    }

    const propertyNodes: TreeDataItem[] = propertyDefinitionList.definitions.map((propertyDefinition) => {
        const propertyPath = `${columnPath}.${propertyDefinition.name}`
        const hogqlExpression = `${escapeDottedHogQLIdentifier(columnPath)}.${escapeRawPropertyAsHogQLIdentifier(
            propertyDefinition.name
        )}`

        const propertyNode = createColumnNode(
            tableName,
            {
                id: propertyDefinition.id,
                name: propertyDefinition.name,
                hogql_value: propertyDefinition.name,
                type: getPropertyDefinitionFieldType(propertyDefinition),
                schema_valid: true,
            },
            propertyPath,
            isSearch,
            hogqlExpression
        )

        return {
            ...propertyNode,
            record: {
                ...propertyNode.record,
                propertyDefinition,
            },
        }
    })

    if (propertyDefinitionList.loading) {
        propertyNodes.push({
            id: `${isSearch ? 'search-' : ''}property-${tableName}-${columnPath}-loading/`,
            name: 'Loading...',
            displayName: <>Loading...</>,
            icon: <Spinner />,
            disableSelect: true,
            type: 'loading-indicator',
        })
    } else if (propertyDefinitionList.error) {
        propertyNodes.push(
            {
                id: `${isSearch ? 'search-' : ''}property-${tableName}-${columnPath}-error/`,
                name: "Couldn't load properties",
                displayName: <span className="text-danger">Couldn't load properties</span>,
                icon: <IconWarning className="text-danger" />,
                disableSelect: true,
                type: 'node',
                record: { type: 'property-definitions-error' },
            },
            {
                id: `${isSearch ? 'search-' : ''}property-${tableName}-${columnPath}-retry/`,
                name: 'Try again',
                displayName: <>Try again</>,
                icon: <IconRefresh />,
                onClick: () => loadPropertyDefinitions?.(propertyFieldKey, target, 0),
                record: { type: 'property-definitions-retry' },
            }
        )
    } else if (propertyDefinitionList.definitions.length < propertyDefinitionList.count) {
        propertyNodes.push({
            id: `${isSearch ? 'search-' : ''}property-${tableName}-${columnPath}-load-more/`,
            name: 'Load more',
            displayName: <>Load more</>,
            icon: <IconPlus />,
            onClick: () =>
                loadPropertyDefinitions?.(propertyFieldKey, target, propertyDefinitionList.definitions.length),
            record: { type: 'property-definitions-load-more' },
        })
    } else if (propertyNodes.length === 0) {
        propertyNodes.push({
            id: `${isSearch ? 'search-' : ''}property-${tableName}-${columnPath}-empty/`,
            name: propertyDefinitionList.search ? 'No matching properties' : 'No properties found',
            type: 'empty-folder',
            record: { type: 'empty-folder' },
        })
    }

    return propertyNodes
}

const createPropertyDefinitionFieldNode = (
    tableName: string,
    field: DatabaseSchemaField,
    isSearch: boolean,
    columnPath: string,
    target: SidebarPropertyDefinitionTarget,
    options: FieldTraversalOptions
): TreeDataItem => {
    const propertyFieldKey = `${tableName}:${columnPath}`
    const propertyDefinitionList = options.propertyDefinitionLists?.[propertyFieldKey]

    return {
        id: `${isSearch ? 'search-' : ''}property-${tableName}-${columnPath}`,
        name: field.name,
        type: 'node',
        icon: <IconBrackets />,
        record: {
            type: 'property-field',
            columnName: columnPath,
            field,
            propertyDefinitionKey: propertyFieldKey,
            propertyDefinitionSearch: propertyDefinitionList?.search ?? '',
            propertyDefinitionTarget: target,
            table: tableName,
        },
        children: createPropertyDefinitionChildren(
            tableName,
            columnPath,
            isSearch,
            propertyFieldKey,
            target,
            propertyDefinitionList,
            options.loadPropertyDefinitions
        ),
    }
}

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

// Placeholder shown while a table's fields are being lazy loaded. `pendingTableName` marks the
// table to hydrate; the tree subscription collects these for every visible placeholder.
const createPendingFieldsNode = (nodeId: string, pendingTableName: string): TreeDataItem => {
    return {
        id: `${nodeId}-fields-pending/`,
        name: 'Loading...',
        displayName: <>Loading...</>,
        icon: <Spinner />,
        disableSelect: true,
        type: 'loading-indicator',
        record: {
            type: 'pending-fields',
            pendingTableName,
        },
    }
}

const createFieldsErrorNode = (nodeId: string): TreeDataItem => {
    return {
        id: `${nodeId}-fields-error/`,
        name: "Couldn't load columns",
        displayName: <span className="text-danger">Couldn't load columns</span>,
        icon: <IconWarning className="text-danger" />,
        disableSelect: true,
        type: 'node',
        record: {
            type: 'fields-load-error',
        },
    }
}

// A failed schema load must not look like an empty project: say it failed and offer the retry.
const createSchemaErrorNodes = (prefix: string, onRetry: () => void): TreeDataItem[] => [
    {
        id: `${prefix}-error/`,
        name: "Couldn't load your schema",
        displayName: <span className="text-danger">Couldn't load your schema</span>,
        icon: <IconWarning className="text-danger" />,
        disableSelect: true,
        type: 'node',
        record: {
            type: 'schema-load-error',
        },
    },
    {
        id: `${prefix}-error-retry/`,
        name: 'Try again',
        displayName: <>Try again</>,
        icon: <IconRefresh />,
        onClick: onRetry,
        record: {
            type: 'schema-load-retry',
        },
    },
]

const createDirectConnectionEmptyNodes = (connectionId: string): TreeDataItem[] => [
    {
        id: 'direct-connection-empty/',
        name: 'No queryable tables',
        displayName: <>No queryable tables</>,
        icon: <IconDatabase />,
        disableSelect: true,
        type: 'node',
        record: {
            type: 'direct-connection-empty',
        },
    },
    {
        id: 'direct-connection-configure/',
        name: 'Configure tables',
        displayName: <>Configure tables</>,
        icon: <IconPlus />,
        onClick: () => newInternalTab(urls.dataWarehouseSource(`managed-${connectionId}`, 'schemas')),
        record: {
            type: 'direct-connection-configure',
        },
    },
]

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

// Children of an expanded lazy-join node. When the joined table exists but its fields haven't been
// lazy loaded yet, show a hydration placeholder instead of a false "Empty folder".
const createExpandedLazyTableChildren = (
    lazyNodeId: string,
    tableName: string,
    field: DatabaseSchemaField,
    isSearch: boolean,
    columnPath: string,
    tableLookup: TableLookup | undefined,
    options: FieldTraversalOptions | undefined
): TreeDataItem[] => {
    const normalizedTableName = normalizeTableLookupKey(field.table)
    const referencedTable = field.table
        ? (tableLookup?.[field.table] ?? (normalizedTableName ? tableLookup?.[normalizedTableName] : undefined))
        : undefined

    if (referencedTable) {
        const state = getTableFieldsState(referencedTable.name, referencedTable.fields, options?.hydration)
        if (state === 'pending') {
            return [createPendingFieldsNode(lazyNodeId, referencedTable.name)]
        }
        if (state === 'error') {
            return [createFieldsErrorNode(lazyNodeId)]
        }
    }

    const lazyChildren = createLazyTableChildren(tableName, field, isSearch, columnPath, tableLookup, {
        ...options,
        expandedLazyNodeIds: options?.expandedLazyNodeIds ?? new Set<string>(),
    })
    return lazyChildren.length > 0 ? lazyChildren : [createLazyTableEmptyNode(lazyNodeId)]
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
    const children = isExpanded
        ? createExpandedLazyTableChildren(
              lazyNodeId,
              tableName,
              traversedField,
              isSearch,
              columnPath,
              tableLookup,
              options
          )
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
        propertyDefinitionLists: options?.propertyDefinitionLists,
        loadPropertyDefinitions: options?.loadPropertyDefinitions,
        allowPropertyDefinitionExpansion: options?.allowPropertyDefinitionExpansion,
        visitedColumnPaths: nextVisitedColumnPaths,
        depth: depth + 1,
        hydration: options?.hydration,
    }
    const propertyDefinitionTarget = options?.allowPropertyDefinitionExpansion
        ? getSidebarPropertyDefinitionTarget(tableName, columnPath, field)
        : null
    if (propertyDefinitionTarget) {
        return createPropertyDefinitionFieldNode(
            tableName,
            field,
            isSearch,
            columnPath,
            propertyDefinitionTarget,
            nextOptions
        )
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
        const children = isExpanded
            ? createExpandedLazyTableChildren(
                  lazyNodeId,
                  tableName,
                  field,
                  isSearch,
                  columnPath,
                  tableLookup,
                  nextOptions
              )
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
    options?: FieldTraversalOptions
): TreeDataItem => {
    const tableId = `${isSearch ? 'search-' : ''}table-${table.name}`
    const tableChildren: TreeDataItem[] = []

    if ('fields' in table) {
        const fieldsState = getTableFieldsState(table.name, table.fields, options?.hydration)
        if (fieldsState === 'pending') {
            tableChildren.push(createPendingFieldsNode(tableId, table.name))
        } else if (fieldsState === 'error') {
            tableChildren.push(createFieldsErrorNode(tableId))
        } else {
            sortFieldsWithPrimary(table.name, Object.values(table.fields))
                .filter((field) => !shouldHideField(field))
                .forEach((field: DatabaseSchemaField) => {
                    tableChildren.push(
                        createFieldNode(table.name, field, isSearch, field.name, tableLookup, {
                            expandedLazyNodeIds: options?.expandedLazyNodeIds,
                            propertyDefinitionLists: options?.propertyDefinitionLists,
                            loadPropertyDefinitions: options?.loadPropertyDefinitions,
                            allowPropertyDefinitionExpansion: table.type === 'posthog',
                            hydration: options?.hydration,
                        })
                    )
                })
        }
    }

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
        hydration?: TableFieldsHydration
    },
    schemaTable?: DatabaseSchemaTable,
    isMaterializing = false
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
                    hydration: options?.hydration,
                })
            )
        })

    const viewId = `${isSearch ? 'search-' : ''}view-${view.id}`

    return {
        id: viewId,
        name: view.name,
        type: 'node',
        icon: isMaterializing ? (
            <Spinner />
        ) : isManagedViewsetView ? (
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
            certification: schemaTable?.certification,
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
        hydration?: TableFieldsHydration
    }
): TreeDataItem => {
    const managedViewId = `${isSearch ? 'search-' : ''}managed-view-${managedView.id}`
    const viewChildren: TreeDataItem[] = []

    const fieldsState = getTableFieldsState(managedView.name, managedView.fields, options?.hydration)
    if (fieldsState === 'pending') {
        viewChildren.push(createPendingFieldsNode(managedViewId, managedView.name))
    } else if (fieldsState === 'error') {
        viewChildren.push(createFieldsErrorNode(managedViewId))
    } else {
        sortFieldsWithPrimary(managedView.name, Object.values(managedView.fields))
            .filter((field) => !shouldHideField(field))
            .forEach((field: DatabaseSchemaField) => {
                viewChildren.push(
                    createFieldNode(managedView.name, field, isSearch, field.name, tableLookup, {
                        expandedLazyNodeIds: options?.expandedLazyNodeIds,
                        hydration: options?.hydration,
                    })
                )
            })
    }

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
    options?: { expandedLazyNodeIds?: Set<string>; hydration?: TableFieldsHydration }
): TreeDataItem => {
    const endpointNodeId = `${isSearch ? 'search-' : ''}endpoint-${endpointTable.id}`
    const children: TreeDataItem[] = []
    const fieldsState = getTableFieldsState(endpointTable.name, endpointTable.fields, options?.hydration)
    if (fieldsState === 'pending') {
        children.push(createPendingFieldsNode(endpointNodeId, endpointTable.name))
    } else if (fieldsState === 'error') {
        children.push(createFieldsErrorNode(endpointNodeId))
    } else {
        sortFieldsWithPrimary(endpointTable.name, Object.values(endpointTable.fields))
            .filter((column) => !shouldHideField(column))
            .forEach((column) => {
                children.push(
                    createFieldNode(endpointTable.name, column, isSearch, column.name, tableLookup, {
                        expandedLazyNodeIds: options?.expandedLazyNodeIds,
                        hydration: options?.hydration,
                    })
                )
            })
    }

    const displayName = endpointTable.name.replace(/_v\d+$/, '')

    return {
        id: endpointNodeId,
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
    options?: FieldTraversalOptions
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

    // Distinct ExternalDataSources behind this type folder, so it can link each to its edit page.
    // A type can have several sources (e.g. two Postgres connections), distinguished by prefix.
    const sourceTables = isSearch ? matches.map(([table]) => table) : tables
    const sources: { id: string; label: string }[] = []
    const seenSourceIds = new Set<string>()
    sourceTables.forEach((table) => {
        const source = (table as DatabaseSchemaDataWarehouseTable).source
        if (source?.id && !seenSourceIds.has(source.id)) {
            seenSourceIds.add(source.id)
            // Prefixes are stored with a trailing underscore (e.g. "stripe_"); strip it for display.
            const label = source.prefix?.trim().replace(/_+$/, '') || source.source_type
            sources.push({ id: source.id, label })
        }
    })

    return {
        id: sourceFolderId,
        name: sourceType,
        type: 'node',
        icon: (
            <SourceIcon
                type={
                    sourceType === 'Self-managed' && (tables.length > 0 || matches.length > 0)
                        ? mapUrlToProvider(
                              (tables.length > 0
                                  ? (tables[0] as DatabaseSchemaDataWarehouseTable).url_pattern
                                  : (matches[0][0] as DatabaseSchemaDataWarehouseTable).url_pattern) ?? ''
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
            sources,
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

const getUnloadedPropertyDefinitionRequest = (
    items: TreeDataItem[],
    targetId: string,
    propertyDefinitionLists: Record<string, SidebarPropertyDefinitionList>
): { propertyFieldKey: string; target: SidebarPropertyDefinitionTarget } | null => {
    const propertyField = findTreeItem(items, targetId)
    const propertyFieldKey = propertyField?.record?.propertyDefinitionKey
    const target = propertyField?.record?.propertyDefinitionTarget as SidebarPropertyDefinitionTarget | undefined

    if (
        propertyField?.record?.type !== 'property-field' ||
        typeof propertyFieldKey !== 'string' ||
        !target ||
        propertyDefinitionLists[propertyFieldKey]
    ) {
        return null
    }

    return { propertyFieldKey, target }
}

const getTreeItemDataSourceName = (item: TreeDataItem): string | null => {
    switch (item.record?.type) {
        case 'table':
            return item.record.table?.name ?? item.name
        case 'view':
        case 'managed-view':
            return item.record.view?.name ?? item.name
        case 'endpoint':
            return item.record.tableName ?? item.record.table?.name ?? item.name
        default:
            return null
    }
}

const findDataSourceTreePath = (
    items: TreeDataItem[],
    tableName: string,
    path: TreeDataItem[] = []
): TreeDataItem[] | null => {
    for (const item of items) {
        const nextPath = [...path, item]
        if (getTreeItemDataSourceName(item) === tableName) {
            return nextPath
        }
        if (item.children) {
            const foundPath = findDataSourceTreePath(item.children, tableName, nextPath)
            if (foundPath) {
                return foundPath
            }
        }
    }

    return null
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

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface queryDatabaseLogicValues {
    dataWarehouseSavedQueries: DataWarehouseSavedQuery[] // dataWarehouseViewsLogic
    dataWarehouseSavedQueriesLoading: boolean // dataWarehouseViewsLogic
    dataWarehouseSavedQueryFolders: DataWarehouseSavedQueryFolder[] // dataWarehouseViewsLogic
    dataWarehouseSavedQueryMapById: Record<string, DataWarehouseSavedQuery> // dataWarehouseViewsLogic
    materializingViewIds: string[] // dataWarehouseViewsLogic
    allPosthogTables: DatabaseSchemaTable[] // databaseTableListLogic
    allTablesMap: Record<string, DatabaseSchemaTable> // databaseTableListLogic
    connectionId: string | null // databaseTableListLogic
    dataWarehouseTables: DatabaseSchemaDataWarehouseTable[] // databaseTableListLogic
    dataWarehouseTablesMap: Record<string, DatabaseSchemaDataWarehouseTable | DatabaseSchemaViewTable> // databaseTableListLogic
    databaseFieldsComplete: boolean // databaseTableListLogic
    databaseLoadError: string | null // databaseTableListLogic
    databaseLoading: boolean // databaseTableListLogic
    latestEndpointTables: DatabaseSchemaEndpointTable[] // databaseTableListLogic
    managedViews: DatabaseSchemaManagedViewTable[] // databaseTableListLogic
    posthogTables: DatabaseSchemaTable[] // databaseTableListLogic
    posthogTablesMap: Record<string, DatabaseSchemaTable> // databaseTableListLogic
    systemTables: DatabaseSchemaTable[] // databaseTableListLogic
    systemTablesMap: Record<string, DatabaseSchemaTable> // databaseTableListLogic
    tableFieldsStatus: TableFieldsStatus // databaseTableListLogic
    viewsMapById: Record<string, DatabaseSchemaEndpointTable | DatabaseSchemaManagedViewTable | DatabaseSchemaViewTable> // databaseTableListLogic
    drafts: DataWarehouseSavedQueryDraft[] // draftsLogic
    draftsResponseLoading: boolean // draftsLogic
    hasMoreDrafts: boolean // draftsLogic
    featureFlags: FeatureFlagsSet // featureFlagLogic
    joins: DataWarehouseViewLink[] // joinsLogic
    joinsLoading: boolean // joinsLogic
    dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null // sourceManagementLogic
    currentProjectId: number | string // teamLogic
    user: UserType | null // userLogic
    activeDraggedViewId: string | null
    activeExpandedFolderIds: string[]
    defaultExpandedRootIds: string[]
    displayedTreeData: TreeDataItem[]
    editingDraftId: string | null
    editingPropertyDefinition: EnterprisePropertyDefinitionApi | null
    effectiveDataWarehouseSavedQueries: DataWarehouseSavedQuery[]
    expandedFolders: string[]
    expandedFoldersByConnection: Record<string, string[]>
    expandedItemIds: string[]
    expandedSearchFolders: string[]
    hasNonPosthogSources: boolean
    highlightViewsSectionDrop: boolean
    highlightedDropFolderId: string | null
    joinsByFieldName: Record<string, DataWarehouseViewLink>
    pendingViewFolderOverrides: Record<string, string | null>
    propertyDefinitionLists: Record<string, SidebarPropertyDefinitionList>
    queryTabState: QueryTabState | null
    queryTabStateLoading: boolean
    relevantDataWarehouseTables: [DatabaseSchemaDataWarehouseTable, FuseSearchMatch[] | null][]
    relevantDrafts: [DataWarehouseSavedQueryDraft, FuseSearchMatch[] | null][]
    relevantEndpointTables: [DatabaseSchemaEndpointTable, FuseSearchMatch[] | null][]
    relevantManagedViews: [DatabaseSchemaManagedViewTable, FuseSearchMatch[] | null][]
    relevantPosthogTables: [DatabaseSchemaTable, FuseSearchMatch[] | null][]
    relevantSavedQueries: [DataWarehouseSavedQuery, FuseSearchMatch[] | null][]
    relevantSavedQueryFolders: [DataWarehouseSavedQueryFolder, FuseSearchMatch[] | null][]
    relevantSystemTables: [DatabaseSchemaTable, FuseSearchMatch[] | null][]
    searchTerm: string
    searchTreeData: TreeDataItem[]
    searchTreeMatches: SearchTreeMatches
    searchTreeSourceContext: SearchTreeSourceContext
    selectedDirectSource:
        | {
              job_inputs?: Record<string, any>
          }
        | undefined
    selectedSchema: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery | null
    sidebarOverlayTreeItems: TreeItem[]
    syncMoreNoticeDismissed: boolean
    tableToLocate: string | null
    treeData: TreeDataItem[]
    treeDataContext: TreeDataContext
    treeRef: EditorSidebarTreeRef
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface queryDatabaseLogicActions {
    createDataWarehouseSavedQuerySuccess: (
        dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
        payload?:
            | (Partial<DataWarehouseSavedQuery> & {
                  dag_id?: string
                  folder_id?: string | null
                  types: string[][]
              })
            | undefined
    ) => {
        dataWarehouseSavedQueries: DataWarehouseSavedQuery[]
        payload?: Partial<DataWarehouseSavedQuery> & {
            dag_id?: string
            folder_id?: string | null
            types: string[][]
        }
    } // dataWarehouseViewsLogic
    updateDataWarehouseSavedQuery: (
        view: Partial<DataWarehouseSavedQuery> & {
            edited_history_id?: string
            folder_id?: string | null
            id: string
            lifecycle?: string
            shouldRematerialize?: boolean
            soft_update?: boolean
            sync_frequency?: string
            types?: string[][]
        }
    ) => Partial<DataWarehouseSavedQuery> & {
        edited_history_id?: string
        folder_id?: string | null
        id: string
        lifecycle?: string
        shouldRematerialize?: boolean
        soft_update?: boolean
        sync_frequency?: string
        types?: string[][]
    } // dataWarehouseViewsLogic
    updateDataWarehouseSavedQueryFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    } // dataWarehouseViewsLogic
    updateDataWarehouseSavedQuerySuccess: (
        dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
        payload?:
            | (Partial<DataWarehouseSavedQuery> & {
                  edited_history_id?: string
                  folder_id?: string | null
                  id: string
                  lifecycle?: string
                  shouldRematerialize?: boolean
                  soft_update?: boolean
                  sync_frequency?: string
                  types?: string[][]
              })
            | undefined
    ) => {
        dataWarehouseSavedQueries: DataWarehouseSavedQuery[]
        payload?: Partial<DataWarehouseSavedQuery> & {
            edited_history_id?: string
            folder_id?: string | null
            id: string
            lifecycle?: string
            shouldRematerialize?: boolean
            soft_update?: boolean
            sync_frequency?: string
            types?: string[][]
        }
    } // dataWarehouseViewsLogic
    ensureAllTableFields: () => {
        value: true
    } // databaseTableListLogic
    hydrateTableFields: (tableNames: string[]) => {
        tableNames: string[]
    } // databaseTableListLogic
    refreshDatabaseSchema: () => {
        value: true
    } // databaseTableListLogic
    loadDrafts: () => any // draftsLogic
    loadMoreDrafts: () => any // draftsLogic
    renameDraft: (
        draftId: string,
        name: string
    ) => {
        draftId: string
        name: string
    } // draftsLogic
    deleteJoin: (join: DataWarehouseViewLink) => {
        join: DataWarehouseViewLink
    } // sourceManagementLogic
    toggleEditJoinModal: (join: DataWarehouseViewLink) => {
        join: DataWarehouseViewLink
    } // viewLinkLogic
    toggleJoinTableModal: () => {
        value: true
    } // viewLinkLogic
    clearDraggedViewState: () => {
        value: true
    }
    clearPendingViewFolderOverride: (viewId: string) => {
        viewId: string
    }
    clearPendingViewFolderOverrides: () => {
        value: true
    }
    clearSearch: () => {
        value: true
    }
    clearTableToLocate: () => {
        value: true
    }
    closePropertyDefinitionEditor: () => {
        value: true
    }
    deleteUnsavedQuery: (record: Record<string, any>) => {
        record: Record<string, any>
    }
    deleteUnsavedQueryFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    deleteUnsavedQuerySuccess: (
        queryTabState:
            | QueryTabState
            | {
                  id: string
                  state: {
                      editorModelsStateKey: string
                  }
              }
            | null,
        payload?: {
            record: Record<string, any>
        }
    ) => {
        queryTabState:
            | QueryTabState
            | {
                  id: string
                  state: {
                      editorModelsStateKey: string
                  }
              }
            | null
        payload?: {
            record: Record<string, any>
        }
    }
    loadPropertyDefinitions: (
        propertyFieldKey: string,
        target: SidebarPropertyDefinitionTarget,
        offset: number
    ) => {
        offset: number
        propertyFieldKey: string
        requestId: string
        target: SidebarPropertyDefinitionTarget
    }
    loadPropertyDefinitionsFailure: (
        propertyFieldKey: string,
        search: string,
        requestId: string
    ) => {
        propertyFieldKey: string
        requestId: string
        search: string
    }
    loadPropertyDefinitionsSuccess: (
        propertyFieldKey: string,
        search: string,
        offset: number,
        requestId: string,
        response: {
            count: number
            results: EnterprisePropertyDefinitionApi[]
        }
    ) => {
        offset: number
        propertyFieldKey: string
        requestId: string
        response: {
            count: number
            results: EnterprisePropertyDefinitionApi[]
        }
        search: string
    }
    loadQueryTabState: () => any
    loadQueryTabStateFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadQueryTabStateSuccess: (
        queryTabState: QueryTabState | null,
        payload?: any
    ) => {
        queryTabState: QueryTabState | null
        payload?: any
    }
    locateTable: (tableName: string) => {
        tableName: string
    }
    moveDraggedViewToDropTarget: (
        viewId: string,
        dropTargetId: string | null
    ) => {
        dropTargetId: string | null
        viewId: string
    }
    openPropertyDefinitionEditor: (propertyDefinition: EnterprisePropertyDefinitionApi) => {
        propertyDefinition: EnterprisePropertyDefinitionApi
    }
    openUnsavedQuery: (record: Record<string, any>) => {
        record: Record<string, any>
    }
    selectSchema: (schema: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery) => {
        schema: DatabaseSchemaTable | DataWarehouseSavedQuery
    }
    selectSourceTable: (tableName: string) => {
        tableName: string
    }
    setDraggedViewDropState: (
        folderId: string | null,
        isViewsSectionDrop: boolean
    ) => {
        folderId: string | null
        isViewsSectionDrop: boolean
    }
    setEditingDraft: (draftId: string) => {
        draftId: string
    }
    setExpandedFolders: (
        folderIds: string[],
        connectionId?: string | null
    ) => {
        connectionId: string | null | undefined
        folderIds: string[]
    }
    setExpandedSearchFolders: (folderIds: string[]) => {
        folderIds: string[]
    }
    setPendingViewFolderOverride: (
        viewId: string,
        folderId: string | null
    ) => {
        folderId: string | null
        viewId: string
    }
    setPropertyDefinitionSearch: (
        propertyFieldKey: string,
        target: SidebarPropertyDefinitionTarget,
        search: string
    ) => {
        propertyFieldKey: string
        search: string
        target: SidebarPropertyDefinitionTarget
    }
    setSearchTerm: (searchTerm: string) => {
        searchTerm: string
    }
    setSyncMoreNoticeDismissed: (dismissed: boolean) => {
        dismissed: boolean
    }
    setTreeRef: (ref: EditorSidebarTreeRef | null) => {
        ref: EditorSidebarTreeRef
    }
    startDraggingView: (viewId: string) => {
        viewId: string
    }
    toggleFolderOpen: (
        folderId: string,
        isExpanded: boolean
    ) => {
        folderId: string
        isExpanded: boolean
    }
    updateDraggedViewDropTarget: (dropTargetId: string | null) => {
        dropTargetId: string | null
    }
    updatePropertyDefinition: (propertyDefinition: EnterprisePropertyDefinitionApi) => {
        propertyDefinition: EnterprisePropertyDefinitionApi
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface queryDatabaseLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        hasNonPosthogSources: (dataWarehouseTables: DatabaseSchemaDataWarehouseTable[]) => boolean
        relevantPosthogTables: (
            posthogTables: DatabaseSchemaTable[],
            searchTerm: string
        ) => [DatabaseSchemaTable, FuseSearchMatch[] | null][]
        relevantSystemTables: (
            systemTables: DatabaseSchemaTable[],
            searchTerm: string
        ) => [DatabaseSchemaTable, FuseSearchMatch[] | null][]
        relevantDataWarehouseTables: (
            dataWarehouseTables: DatabaseSchemaDataWarehouseTable[],
            searchTerm: string
        ) => [DatabaseSchemaDataWarehouseTable, FuseSearchMatch[] | null][]
        relevantSavedQueries: (
            effectiveDataWarehouseSavedQueries: DataWarehouseSavedQuery[],
            searchTerm: string
        ) => [DataWarehouseSavedQuery, FuseSearchMatch[] | null][]
        relevantSavedQueryFolders: (
            dataWarehouseSavedQueryFolders: DataWarehouseSavedQueryFolder[],
            searchTerm: string
        ) => [DataWarehouseSavedQueryFolder, FuseSearchMatch[] | null][]
        effectiveDataWarehouseSavedQueries: (
            dataWarehouseSavedQueries: DataWarehouseSavedQuery[],
            pendingViewFolderOverrides: Record<string, string | null>
        ) => DataWarehouseSavedQuery[]
        relevantManagedViews: (
            managedViews: DatabaseSchemaManagedViewTable[],
            searchTerm: string
        ) => [DatabaseSchemaManagedViewTable, FuseSearchMatch[] | null][]
        relevantDrafts: (
            drafts: DataWarehouseSavedQueryDraft[],
            searchTerm: string
        ) => [DataWarehouseSavedQueryDraft, FuseSearchMatch[] | null][]
        relevantEndpointTables: (
            latestEndpointTables: DatabaseSchemaEndpointTable[],
            searchTerm: string
        ) => [DatabaseSchemaEndpointTable, FuseSearchMatch[] | null][]
        selectedDirectSource: (
            dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null,
            connectionId: string | null
        ) =>
            | {
                  job_inputs?: Record<string, any>
              }
            | undefined
        searchTreeSourceContext: (
            allPosthogTables: DatabaseSchemaTable[],
            systemTables: DatabaseSchemaTable[],
            dataWarehouseTables: DatabaseSchemaDataWarehouseTable[],
            effectiveDataWarehouseSavedQueries: DataWarehouseSavedQuery[],
            dataWarehouseSavedQueryFolders: DataWarehouseSavedQueryFolder[],
            managedViews: DatabaseSchemaManagedViewTable[],
            allTablesMap: Record<string, DatabaseSchemaTable>
        ) => SearchTreeSourceContext
        searchTreeMatches: (
            relevantPosthogTables: [DatabaseSchemaTable, FuseSearchMatch[] | null][],
            relevantSystemTables: [DatabaseSchemaTable, FuseSearchMatch[] | null][],
            relevantDataWarehouseTables: [DatabaseSchemaDataWarehouseTable, FuseSearchMatch[] | null][],
            relevantSavedQueries: [DataWarehouseSavedQuery, FuseSearchMatch[] | null][],
            relevantSavedQueryFolders: [DataWarehouseSavedQueryFolder, FuseSearchMatch[] | null][],
            relevantManagedViews: [DatabaseSchemaManagedViewTable, FuseSearchMatch[] | null][],
            relevantDrafts: [DataWarehouseSavedQueryDraft, FuseSearchMatch[] | null][],
            relevantEndpointTables: [DatabaseSchemaEndpointTable, FuseSearchMatch[] | null][]
        ) => SearchTreeMatches
        searchTreeData: (
            searchTreeSourceContext: SearchTreeSourceContext,
            searchTreeMatches: SearchTreeMatches,
            searchTerm: string,
            featureFlags: FeatureFlagsSet,
            expandedSearchFolders: string[],
            materializingViewIds: string[],
            propertyDefinitionLists: Record<string, SidebarPropertyDefinitionList>
        ) => TreeDataItem[]
        treeDataContext: (
            allPosthogTables: DatabaseSchemaTable[],
            posthogTables: DatabaseSchemaTable[],
            systemTables: DatabaseSchemaTable[],
            dataWarehouseTables: DatabaseSchemaDataWarehouseTable[],
            effectiveDataWarehouseSavedQueries: DataWarehouseSavedQuery[],
            dataWarehouseSavedQueryFolders: DataWarehouseSavedQueryFolder[],
            managedViews: DatabaseSchemaManagedViewTable[],
            latestEndpointTables: DatabaseSchemaEndpointTable[],
            allTablesMap: Record<string, DatabaseSchemaTable>
        ) => TreeDataContext
        treeData: (
            treeDataContext: TreeDataContext,
            databaseLoading: boolean,
            databaseLoadError: string | null,
            dataWarehouseSavedQueriesLoading: boolean,
            drafts: DataWarehouseSavedQueryDraft[],
            draftsResponseLoading: boolean,
            hasMoreDrafts: boolean,
            featureFlags: FeatureFlagsSet,
            queryTabState: QueryTabState | null,
            expandedFolders: string[],
            materializingViewIds: string[],
            propertyDefinitionLists: Record<string, SidebarPropertyDefinitionList>,
            databaseFieldsComplete: boolean,
            tableFieldsStatus: TableFieldsStatus
        ) => TreeDataItem[]
        displayedTreeData: (
            searchTerm: string,
            searchTreeData: TreeDataItem[],
            treeData: TreeDataItem[],
            connectionId: string | null,
            selectedDirectSource:
                | {
                      job_inputs?: Record<string, any>
                  }
                | undefined,
            databaseLoading: boolean,
            databaseLoadError: string | null,
            allTablesMap: Record<string, DatabaseSchemaTable>
        ) => TreeDataItem[]
        activeExpandedFolderIds: (
            searchTerm: string,
            expandedSearchFolders: string[],
            expandedFolders: string[]
        ) => string[]
        expandedFolders: (
            connectionId: string | null,
            expandedFoldersByConnection: Record<string, string[]>
        ) => string[]
        defaultExpandedRootIds: (connectionId: string | null, displayedTreeData: TreeDataItem[]) => string[]
        expandedItemIds: (activeExpandedFolderIds: string[], defaultExpandedRootIds: string[]) => string[]
        joinsByFieldName: (joins: DataWarehouseViewLink[]) => Record<string, DataWarehouseViewLink>
        sidebarOverlayTreeItems: (
            selectedSchema: DatabaseSchemaTable | DataWarehouseSavedQuery | null,
            posthogTablesMap: Record<string, DatabaseSchemaTable>,
            systemTablesMap: Record<string, DatabaseSchemaTable>,
            dataWarehouseTablesMap: Record<string, DatabaseSchemaDataWarehouseTable | DatabaseSchemaViewTable>,
            dataWarehouseSavedQueryMapById: Record<string, DataWarehouseSavedQuery>,
            viewsMapById: Record<
                string,
                DatabaseSchemaEndpointTable | DatabaseSchemaManagedViewTable | DatabaseSchemaViewTable
            >,
            joinsByFieldName: Record<string, DataWarehouseViewLink>
        ) => TreeItem[]
    }
}

export type queryDatabaseLogicType = MakeLogicType<
    queryDatabaseLogicValues,
    queryDatabaseLogicActions,
    Record<string, any>,
    queryDatabaseLogicMeta
>

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
        setPropertyDefinitionSearch: (
            propertyFieldKey: string,
            target: SidebarPropertyDefinitionTarget,
            search: string
        ) => ({ propertyFieldKey, target, search }),
        loadPropertyDefinitions: (
            propertyFieldKey: string,
            target: SidebarPropertyDefinitionTarget,
            offset: number
        ) => ({ propertyFieldKey, target, offset, requestId: uuid() }),
        loadPropertyDefinitionsSuccess: (
            propertyFieldKey: string,
            search: string,
            offset: number,
            requestId: string,
            response: { count: number; results: EnterprisePropertyDefinitionApi[] }
        ) => ({ propertyFieldKey, search, offset, requestId, response }),
        loadPropertyDefinitionsFailure: (propertyFieldKey: string, search: string, requestId: string) => ({
            propertyFieldKey,
            search,
            requestId,
        }),
        openPropertyDefinitionEditor: (propertyDefinition: EnterprisePropertyDefinitionApi) => ({
            propertyDefinition,
        }),
        closePropertyDefinitionEditor: true,
        updatePropertyDefinition: (propertyDefinition: EnterprisePropertyDefinitionApi) => ({ propertyDefinition }),
        clearSearch: true,
        clearTableToLocate: true,
        locateTable: (tableName: string) => ({ tableName }),
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
                'databaseLoadError',
                'systemTables',
                'systemTablesMap',
                'allTablesMap',
                'latestEndpointTables',
                'connectionId',
                'databaseFieldsComplete',
                'tableFieldsStatus',
            ],
            dataWarehouseViewsLogic,
            [
                'dataWarehouseSavedQueries',
                'dataWarehouseSavedQueryFolders',
                'dataWarehouseSavedQueryMapById',
                'dataWarehouseSavedQueriesLoading',
                'materializingViewIds',
            ],
            draftsLogic,
            ['drafts', 'draftsResponseLoading', 'hasMoreDrafts'],
            sourceManagementLogic,
            ['dataWarehouseSources'],
            featureFlagLogic,
            ['featureFlags'],
            teamLogic,
            ['currentProjectId'],
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
            databaseTableListLogic,
            ['refreshDatabaseSchema', 'hydrateTableFields', 'ensureAllTableFields'],
        ],
    })),
    reducers({
        editingDraftId: [
            null as string | null,
            {
                setEditingDraft: (_, { draftId }) => draftId,
            },
        ],
        editingPropertyDefinition: [
            null as EnterprisePropertyDefinitionApi | null,
            {
                openPropertyDefinitionEditor: (_, { propertyDefinition }) => propertyDefinition,
                closePropertyDefinitionEditor: () => null,
                updatePropertyDefinition: () => null,
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
        tableToLocate: [
            null as string | null,
            {
                locateTable: (_, { tableName }) => tableName,
                clearTableToLocate: () => null,
            },
        ],

        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
                clearSearch: () => '',
            },
        ],
        propertyDefinitionLists: [
            {} as Record<string, SidebarPropertyDefinitionList>,
            {
                setPropertyDefinitionSearch: (state, { propertyFieldKey, search }) => ({
                    ...state,
                    [propertyFieldKey]: {
                        activeRequestId: null,
                        count: 0,
                        definitions: [],
                        error: false,
                        loading: true,
                        search,
                    },
                }),
                loadPropertyDefinitions: (state, { propertyFieldKey, offset, requestId }) => {
                    const current = state[propertyFieldKey] ?? {
                        activeRequestId: null,
                        count: 0,
                        definitions: [],
                        error: false,
                        loading: false,
                        search: '',
                    }

                    return {
                        ...state,
                        [propertyFieldKey]: {
                            ...current,
                            activeRequestId: requestId,
                            definitions: offset === 0 ? [] : current.definitions,
                            error: false,
                            loading: true,
                        },
                    }
                },
                loadPropertyDefinitionsSuccess: (state, { propertyFieldKey, search, offset, requestId, response }) => {
                    const current = state[propertyFieldKey]
                    if (!current || current.search !== search || current.activeRequestId !== requestId) {
                        return state
                    }

                    const definitions = offset === 0 ? response.results : [...current.definitions, ...response.results]
                    return {
                        ...state,
                        [propertyFieldKey]: {
                            ...current,
                            activeRequestId: null,
                            count: response.count,
                            definitions: Array.from(
                                new Map(definitions.map((definition) => [definition.id, definition])).values()
                            ),
                            error: false,
                            loading: false,
                        },
                    }
                },
                loadPropertyDefinitionsFailure: (state, { propertyFieldKey, search, requestId }) => {
                    const current = state[propertyFieldKey]
                    if (!current || current.search !== search || current.activeRequestId !== requestId) {
                        return state
                    }

                    return {
                        ...state,
                        [propertyFieldKey]: {
                            ...current,
                            activeRequestId: null,
                            error: true,
                            loading: false,
                        },
                    }
                },
                updatePropertyDefinition: (state, { propertyDefinition }) =>
                    Object.fromEntries(
                        Object.entries(state).map(([propertyFieldKey, propertyDefinitionList]) => {
                            const includesPropertyDefinition = propertyDefinitionList.definitions.some(
                                (definition) => definition.id === propertyDefinition.id
                            )
                            const definitions = propertyDefinition.hidden
                                ? propertyDefinitionList.definitions.filter(
                                      (definition) => definition.id !== propertyDefinition.id
                                  )
                                : propertyDefinitionList.definitions.map((definition) =>
                                      definition.id === propertyDefinition.id ? propertyDefinition : definition
                                  )

                            return [
                                propertyFieldKey,
                                {
                                    ...propertyDefinitionList,
                                    count:
                                        propertyDefinition.hidden && includesPropertyDefinition
                                            ? Math.max(0, propertyDefinitionList.count - 1)
                                            : propertyDefinitionList.count,
                                    definitions,
                                },
                            ]
                        })
                    ),
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
        setPropertyDefinitionSearch: async ({ propertyFieldKey, target }, breakpoint) => {
            await breakpoint(250)
            actions.loadPropertyDefinitions(propertyFieldKey, target, 0)
        },
        loadPropertyDefinitions: async ({ propertyFieldKey, target, offset, requestId }) => {
            const search = values.propertyDefinitionLists[propertyFieldKey]?.search ?? ''

            try {
                const response = await propertyDefinitionsList(String(values.currentProjectId), {
                    exclude_hidden: true,
                    exclude_restricted: true,
                    group_type_index: target.groupTypeIndex,
                    limit: PROPERTY_DEFINITIONS_PAGE_SIZE,
                    offset,
                    search: search.trim() || undefined,
                    type: target.type,
                })
                actions.loadPropertyDefinitionsSuccess(propertyFieldKey, search, offset, requestId, response)
            } catch {
                actions.loadPropertyDefinitionsFailure(propertyFieldKey, search, requestId)
            }
        },
    })),
    listeners(({ actions, values }) => {
        const revealLocatedTable = (tableName: string): void => {
            actions.clearSearch()
            const path = findDataSourceTreePath(values.displayedTreeData, tableName)
            if (!path) {
                return
            }

            const tableId = path[path.length - 1].id
            actions.setExpandedFolders(
                Array.from(new Set([...values.expandedFolders, ...path.map((item) => item.id)])),
                values.connectionId
            )

            if (values.treeRef?.current) {
                values.treeRef.current.focusItem(tableId, {
                    scrollPosition: 'top-third',
                    behavior: 'smooth',
                })
                actions.clearTableToLocate()
            }
        }

        return {
            locateTable: ({ tableName }) => {
                revealLocatedTable(tableName)
            },
            setTreeRef: ({ ref }) => {
                if (ref?.current && values.tableToLocate) {
                    revealLocatedTable(values.tableToLocate)
                }
            },
        }
    }),
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
    selectors(({ actions, cache }) => ({
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
            (
                dataWarehouseSources: null | import('lib/api').PaginatedResponse<import('~/types').ExternalDataSource>,
                connectionId: string | null
            ): { job_inputs?: Record<string, any> } | undefined => {
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
                s.materializingViewIds,
                s.propertyDefinitionLists,
            ],
            (
                searchTreeSourceContext: SearchTreeSourceContext,
                searchTreeMatches: SearchTreeMatches,
                searchTerm: string,
                featureFlags: FeatureFlagsSet,
                expandedSearchFolders: string[],
                materializingViewIds: string[],
                propertyDefinitionLists: Record<string, SidebarPropertyDefinitionList>
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
                const tableNodeOptions: FieldTraversalOptions = {
                    expandedLazyNodeIds,
                    propertyDefinitionLists,
                    loadPropertyDefinitions: actions.loadPropertyDefinitions,
                }

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
                const materializingViewIdSet = new Set(materializingViewIds)
                relevantSavedQueries.forEach(([view, matches]) => {
                    const schemaTable = getSavedQuerySchemaTable(view, allTablesMap)
                    const viewNode = createViewNode(
                        view,
                        matches,
                        true,
                        tableLookup,
                        tableNodeOptions,
                        schemaTable,
                        materializingViewIdSet.has(view.id)
                    )
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

                // Auto-expand matching groups once per search term, so the user can freely collapse
                // them afterwards without the selector immediately re-expanding them.
                const expandedIdSet = new Set(expandedSearchFolders)
                const missingRequiredExpansion = expandedIds.some((id) => !expandedIdSet.has(id))

                if (missingRequiredExpansion && cache.lastAutoExpandedSearchTerm !== searchTerm) {
                    cache.lastAutoExpandedSearchTerm = searchTerm
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
                s.databaseLoadError,
                s.dataWarehouseSavedQueriesLoading,
                s.drafts,
                s.draftsResponseLoading,
                s.hasMoreDrafts,
                s.featureFlags,
                s.queryTabState,
                s.expandedFolders,
                s.materializingViewIds,
                s.propertyDefinitionLists,
                s.databaseFieldsComplete,
                s.tableFieldsStatus,
            ],
            (
                treeDataContext: TreeDataContext,
                databaseLoading: boolean,
                databaseLoadError: string | null,
                dataWarehouseSavedQueriesLoading: boolean,
                drafts: DataWarehouseSavedQueryDraft[],
                draftsResponseLoading: boolean,
                hasMoreDrafts: boolean,
                featureFlags: FeatureFlagsSet,
                queryTabState: QueryTabState | null,
                expandedFolders: string[],
                materializingViewIds: string[],
                propertyDefinitionLists: Record<string, SidebarPropertyDefinitionList>,
                databaseFieldsComplete: boolean,
                tableFieldsStatus: TableFieldsStatus
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
                const hydration: TableFieldsHydration = { databaseFieldsComplete, tableFieldsStatus }
                const tableNodeOptions: FieldTraversalOptions = {
                    expandedLazyNodeIds,
                    propertyDefinitionLists,
                    loadPropertyDefinitions: actions.loadPropertyDefinitions,
                    hydration,
                }
                const schemaFailedWithNoTables =
                    !!databaseLoadError && !databaseLoading && Object.keys(allTablesMap).length === 0

                if (schemaFailedWithNoTables) {
                    sourcesChildren.push(...createSchemaErrorNodes('sources', () => actions.refreshDatabaseSchema()))
                } else if (databaseLoading && posthogTables.length === 0 && dataWarehouseTables.length === 0) {
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
                    const materializingViewIdSet = new Set(materializingViewIds)

                    // Add saved queries
                    dataWarehouseSavedQueries.forEach((view) => {
                        const schemaTable = getSavedQuerySchemaTable(view, allTablesMap)
                        const viewNode = createViewNode(
                            view,
                            null,
                            false,
                            tableLookup,
                            tableNodeOptions,
                            schemaTable,
                            materializingViewIdSet.has(view.id)
                        )
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

                // Managed views come from the same schema request as sources, so they're missing for
                // the same reason. Replaces the saved-query spinner, which tracks a different request.
                if (schemaFailedWithNoTables && managedViews.length === 0) {
                    managedViewsChildren.length = 0
                    managedViewsChildren.push(
                        ...createSchemaErrorNodes('managed-views', () => actions.refreshDatabaseSchema())
                    )
                }

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
            (s) => [
                s.searchTerm,
                s.searchTreeData,
                s.treeData,
                s.connectionId,
                s.selectedDirectSource,
                s.databaseLoading,
                s.databaseLoadError,
                s.allTablesMap,
            ],
            (
                searchTerm: string,
                searchTreeData: TreeDataItem[],
                treeData: TreeDataItem[],
                connectionId: string | null,
                selectedDirectSource: { job_inputs?: Record<string, any> } | undefined,
                databaseLoading: boolean,
                databaseLoadError: string | null,
                allTablesMap: Record<string, DatabaseSchemaTable>
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

                const hasLoadedTables = Object.keys(allTablesMap).length > 0
                if (!databaseLoading && databaseLoadError) {
                    return [
                        ...createSchemaErrorNodes('direct-connection', () => actions.refreshDatabaseSchema()),
                        ...additionalItems,
                    ]
                }
                if (!databaseLoading && !hasLoadedTables) {
                    return [...createDirectConnectionEmptyNodes(connectionId), ...additionalItems]
                }

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
                selectedSchema: DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable | DataWarehouseSavedQuery | null,
                posthogTablesMap: Record<string, DatabaseSchemaTable>,
                systemTablesMap: Record<string, DatabaseSchemaTable>,
                dataWarehouseTablesMap: Record<
                    string,
                    DatabaseSchemaDataWarehouseTable | import('~/queries/schema/schema-general').DatabaseSchemaViewTable
                >,
                dataWarehouseSavedQueryMapById: Record<string, DataWarehouseSavedQuery>,
                viewsMapById: Record<
                    string,
                    | DatabaseSchemaEndpointTable
                    | DatabaseSchemaManagedViewTable
                    | import('~/queries/schema/schema-general').DatabaseSchemaViewTable
                >,
                joinsByFieldName: Record<string, DataWarehouseViewLink>
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

            if (!isExpanded) {
                const request = getUnloadedPropertyDefinitionRequest(
                    values.displayedTreeData,
                    folderId,
                    values.propertyDefinitionLists
                )
                if (request) {
                    actions.loadPropertyDefinitions(request.propertyFieldKey, request.target, 0)
                }
            }

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
                // With a lazy-loaded schema, expanding a node is what triggers fetching its columns.
                // Going through the tree node (rather than parsing the id) also retries failed loads.
                const node = findTreeItemById(values.displayedTreeData, folderId)
                if (node) {
                    const tableNames = getHydrationTableNamesForNode(node)
                    if (tableNames.length > 0) {
                        actions.hydrateTableFields(tableNames)
                    }
                }
            }
        },
        selectSchema: ({ schema }) => {
            // The sidebar overlay lists the selected table's columns, so make sure they're loaded.
            if (schema && 'name' in schema && schema.name) {
                actions.hydrateTableFields([schema.name])
            }
        },
        setSearchTerm: ({ searchTerm }) => {
            // Search matches on column names too, which a lazy-loaded schema doesn't have yet.
            if (searchTerm) {
                actions.ensureAllTableFields()
            }
        },
        selectSourceTable: ({ tableName }) => {
            // Connect to viewLinkLogic actions
            viewLinkLogic.actions.selectSourceTable(tableName)
            viewLinkLogic.actions.toggleJoinTableModal()
        },
        openUnsavedQuery: ({ record }) => {
            if (record.insight) {
                newInternalTab(urls.sqlEditor({ insightShortId: record.insight.short_id }))
            } else if (record.view) {
                newInternalTab(urls.sqlEditor({ view_id: record.view.id }))
            } else {
                newInternalTab(urls.sqlEditor({ query: record.query }))
            }
        },
    })),
    subscriptions(({ actions, values }) => ({
        displayedTreeData: (displayedTreeData: TreeDataItem[]) => {
            for (const folderId of values.expandedItemIds) {
                const request = getUnloadedPropertyDefinitionRequest(
                    displayedTreeData,
                    folderId,
                    values.propertyDefinitionLists
                )
                if (request) {
                    actions.loadPropertyDefinitions(request.propertyFieldKey, request.target, 0)
                }
            }

            // Hydrate fields for every visible "Loading..." placeholder. Covers expansion restored from
            // persisted state and nodes that were expanded before the shallow schema arrived; the
            // hydrate action itself dedupes tables that are already loading or settled.
            const expanded = new Set(values.searchTerm ? values.expandedSearchFolders : values.expandedFolders)
            const pendingTableNames = new Set<string>()
            const collect = (nodes: TreeDataItem[]): void => {
                for (const node of nodes) {
                    const record = node.record as Record<string, any> | undefined
                    if (record?.type === 'pending-fields' && record.pendingTableName) {
                        pendingTableNames.add(record.pendingTableName)
                        continue
                    }
                    if (node.children && expanded.has(node.id)) {
                        collect(node.children)
                    }
                }
            }
            collect(displayedTreeData)
            if (pendingTableNames.size > 0) {
                actions.hydrateTableFields(Array.from(pendingTableNames))
            }

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
