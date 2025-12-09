import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { directQueryLogicType } from './directQueryLogicType'

export interface DirectQuerySource {
    id: string
    source_type: string
    prefix: string | null
    created_at: string
    status: string
}

export interface DirectQueryResult {
    columns: string[]
    rows: Record<string, any>[]
    row_count: number
    execution_time_ms: number
    error?: string
}

export interface DirectQuerySchemaTable {
    columns: [string, string][] // [column_name, data_type]
}

export interface DirectQuerySchema {
    tables: Record<string, [string, string][]>
}

export type SelectedDatabase = 'hogql' | string // 'hogql' or source ID

export const directQueryLogic = kea<directQueryLogicType>([
    path(['data-warehouse', 'editor', 'directQueryLogic']),
    actions({
        setSelectedDatabase: (database: SelectedDatabase) => ({ database }),
        executeDirectQuery: (sourceId: string, sql: string, maxRows?: number) => ({ sourceId, sql, maxRows }),
        clearQueryResult: true,
        loadSchemaForSource: (sourceId: string) => ({ sourceId }),
    }),
    reducers({
        selectedDatabase: [
            'hogql' as SelectedDatabase,
            {
                setSelectedDatabase: (_: SelectedDatabase, { database }: { database: SelectedDatabase }) => database,
            },
        ],
        currentSchemaSourceId: [
            null as string | null,
            {
                loadSchemaForSource: (_: string | null, { sourceId }: { sourceId: string }) => sourceId,
            },
        ],
    }),
    loaders(() => ({
        sources: [
            [] as DirectQuerySource[],
            {
                loadSources: async (): Promise<DirectQuerySource[]> => {
                    const response = await api.get('api/environments/@current/direct_query/sources')
                    return response.sources || []
                },
            },
        ],
        queryResult: [
            null as DirectQueryResult | null,
            {
                executeDirectQuery: async ({
                    sourceId,
                    sql,
                    maxRows,
                }: {
                    sourceId: string
                    sql: string
                    maxRows?: number
                }): Promise<DirectQueryResult> => {
                    const response = await api.create('api/environments/@current/direct_query/execute', {
                        source_id: sourceId,
                        sql,
                        max_rows: maxRows || 1000,
                    })
                    return response as DirectQueryResult
                },
                clearQueryResult: () => null,
            },
        ],
        schema: [
            null as DirectQuerySchema | null,
            {
                loadSchemaForSource: async ({ sourceId }: { sourceId: string }): Promise<DirectQuerySchema> => {
                    const response = await api.get(`api/environments/@current/direct_query/schema/${sourceId}`)
                    return response as DirectQuerySchema
                },
            },
        ],
    })),
    selectors({
        isDirectQueryMode: [
            (s) => [s.selectedDatabase],
            (selectedDatabase: SelectedDatabase): boolean => selectedDatabase !== 'hogql',
        ],
        selectedSource: [
            (s) => [s.selectedDatabase, s.sources],
            (selectedDatabase: SelectedDatabase, sources: DirectQuerySource[]): DirectQuerySource | null => {
                if (selectedDatabase === 'hogql') {
                    return null
                }
                return sources.find((source: DirectQuerySource) => source.id === selectedDatabase) || null
            },
        ],
        selectedSourceName: [
            (s) => [s.selectedSource],
            (selectedSource: DirectQuerySource | null): string => {
                if (!selectedSource) {
                    return 'PostHog (HogQL)'
                }
                return selectedSource.prefix || selectedSource.source_type
            },
        ],
        databaseOptions: [
            (s) => [s.sources],
            (sources: DirectQuerySource[]): { value: SelectedDatabase; label: string }[] => {
                const options: { value: SelectedDatabase; label: string }[] = [
                    { value: 'hogql', label: 'PostHog (HogQL)' },
                ]
                for (const source of sources) {
                    options.push({
                        value: source.id,
                        label: source.prefix || source.source_type,
                    })
                }
                return options
            },
        ],
        hasDirectQuerySources: [(s) => [s.sources], (sources: DirectQuerySource[]): boolean => sources.length > 0],
    }),
    listeners(({ actions }) => ({
        setSelectedDatabase: ({ database }: { database: SelectedDatabase }) => {
            // Load schema when selecting an external database
            if (database !== 'hogql') {
                actions.loadSchemaForSource(database)
            }
        },
    })),
])
