import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { performQuery } from '~/queries/query'
import { DatabaseSchemaTable, HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { escapePropertyAsHogQLIdentifier, setLatestVersionsOnQuery } from '~/queries/utils'

import { LocalFrameSummary, collectLocalFrames } from '../Nodes/notebookNodeContent'
import { notebookLogic } from './notebookLogic'
import type { notebookSchemaBrowserLogicType } from './notebookSchemaBrowserLogicType'

export type NotebookSchemaBrowserProps = {
    shortId: string
}

export type SchemaBrowserSelection = { type: 'frame'; nodeId: string } | { type: 'table'; tableName: string } | null

export type CatalogTablePreview = {
    tableName: string
    columns: string[]
    rows: any[][]
}

export const CATALOG_PREVIEW_LIMIT = 25

const matchesSearch = (name: string, searchTerm: string): boolean =>
    name.toLowerCase().includes(searchTerm.toLowerCase())

export const notebookSchemaBrowserLogic = kea<notebookSchemaBrowserLogicType>([
    props({} as NotebookSchemaBrowserProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'notebookSchemaBrowserLogic', key]),
    key(({ shortId }) => shortId),
    connect(({ shortId }: NotebookSchemaBrowserProps) => ({
        values: [
            notebookLogic({ shortId }),
            ['content'],
            databaseTableListLogic,
            ['posthogTables', 'dataWarehouseTables', 'views', 'databaseLoading'],
        ],
        actions: [databaseTableListLogic, ['loadDatabase']],
    })),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setSelection: (selection: SchemaBrowserSelection) => ({ selection }),
        previewCatalogTable: (tableName: string) => ({ tableName }),
    }),
    loaders(() => ({
        tablePreview: [
            null as CatalogTablePreview | null,
            {
                previewCatalogTable: async ({ tableName }, breakpoint) => {
                    const query: HogQLQuery = setLatestVersionsOnQuery({
                        kind: NodeKind.HogQLQuery,
                        query: `SELECT * FROM ${escapePropertyAsHogQLIdentifier(tableName)} LIMIT ${CATALOG_PREVIEW_LIMIT}`,
                    })
                    const response = await performQuery(query)
                    breakpoint()
                    return {
                        tableName,
                        columns: (response.columns ?? []).map((column) => String(column)),
                        rows: (response.results ?? []) as any[][],
                    }
                },
            },
        ],
    })),
    reducers({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        selection: [
            null as SchemaBrowserSelection,
            {
                setSelection: (_, { selection }) => selection,
            },
        ],
        tablePreview: {
            // A stale preview must not carry over to a newly selected item.
            setSelection: () => null,
        },
    }),
    selectors({
        localFrames: [(s) => [s.content], (content): LocalFrameSummary[] => collectLocalFrames(content)],
        filteredFrames: [
            (s) => [s.localFrames, s.searchTerm],
            (localFrames: LocalFrameSummary[], searchTerm: string): LocalFrameSummary[] =>
                searchTerm
                    ? localFrames.filter(
                          (frame) => matchesSearch(frame.name, searchTerm) || matchesSearch(frame.title, searchTerm)
                      )
                    : localFrames,
        ],
        filteredPosthogTables: [
            (s) => [s.posthogTables, s.searchTerm],
            (posthogTables: DatabaseSchemaTable[], searchTerm: string): DatabaseSchemaTable[] =>
                searchTerm ? posthogTables.filter((table) => matchesSearch(table.name, searchTerm)) : posthogTables,
        ],
        filteredWarehouseTables: [
            (s) => [s.dataWarehouseTables, s.searchTerm],
            (dataWarehouseTables: DatabaseSchemaTable[], searchTerm: string): DatabaseSchemaTable[] =>
                searchTerm
                    ? dataWarehouseTables.filter((table) => matchesSearch(table.name, searchTerm))
                    : dataWarehouseTables,
        ],
        filteredViews: [
            (s) => [s.views, s.searchTerm],
            (views: DatabaseSchemaTable[], searchTerm: string): DatabaseSchemaTable[] =>
                searchTerm ? views.filter((view) => matchesSearch(view.name, searchTerm)) : views,
        ],
        selectedFrame: [
            (s) => [s.localFrames, s.selection],
            (localFrames: LocalFrameSummary[], selection: SchemaBrowserSelection): LocalFrameSummary | null =>
                selection?.type === 'frame'
                    ? (localFrames.find((frame) => frame.nodeId === selection.nodeId) ?? null)
                    : null,
        ],
        selectedTable: [
            (s) => [s.posthogTables, s.dataWarehouseTables, s.views, s.selection],
            (
                posthogTables: DatabaseSchemaTable[],
                dataWarehouseTables: DatabaseSchemaTable[],
                views: DatabaseSchemaTable[],
                selection: SchemaBrowserSelection
            ): DatabaseSchemaTable | null =>
                selection?.type === 'table'
                    ? ([...posthogTables, ...dataWarehouseTables, ...views].find(
                          (table) => table.name === selection.tableName
                      ) ?? null)
                    : null,
        ],
    }),
    afterMount(({ actions }) => {
        // Deduplicated inside databaseTableListLogic, so a warm cache costs nothing.
        actions.loadDatabase()
    }),
])
