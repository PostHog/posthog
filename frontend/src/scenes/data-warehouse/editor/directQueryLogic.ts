import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { NodeKind } from '~/queries/schema/schema-general'

import type { directQueryLogicType } from './directQueryLogicType'

export interface DirectQuerySource {
    id: string
    source_type: string
    prefix: string | null
    created_at: string
    status: string
}

// Response format from the unified /query/ endpoint for DirectQuery
export interface DirectQueryResult {
    results: Record<string, any>[]
    columns?: string[]
    types?: string[]
    hasMore?: boolean
    executionTimeMs?: number
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
    loaders(({ values }) => ({
        sources: [
            [] as DirectQuerySource[],
            {
                loadSources: async (): Promise<DirectQuerySource[]> => {
                    try {
                        const response = await api.get('api/environments/@current/direct_query/sources/')
                        return response.sources || []
                    } catch (e) {
                        // Return empty array on error - don't block the UI
                        console.error('Failed to load direct query sources:', e)
                        return []
                    }
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
                    // Find the source to get its prefix
                    const source = values.sources.find((s: DirectQuerySource) => s.id === sourceId)
                    let transformedSql = sql

                    // Strip HogQL table path prefixes from the SQL
                    // Tables are referenced as "source_type.prefix.table_name" or "source_type.table_name" in HogQL
                    // but need to be just "table_name" for the external database
                    if (source) {
                        const sourceType = source.source_type.toLowerCase()
                        if (source.prefix) {
                            // Strip "source_type.prefix." (e.g., "postgres.northwind.")
                            const fullPrefixPattern = new RegExp(`\\b${sourceType}\\.${source.prefix}\\.`, 'gi')
                            transformedSql = transformedSql.replace(fullPrefixPattern, '')
                        } else {
                            // Strip "source_type." (e.g., "postgres.")
                            const sourceTypePattern = new RegExp(`\\b${sourceType}\\.`, 'gi')
                            transformedSql = transformedSql.replace(sourceTypePattern, '')
                        }
                    }

                    // Use the unified /query/ endpoint with DirectQuery kind
                    const response = await api.query({
                        kind: NodeKind.DirectQuery,
                        sourceId: sourceId,
                        query: transformedSql,
                        limit: maxRows || 1000,
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
                    const response = await api.get(`api/environments/@current/direct_query/schema/${sourceId}/`)
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
            (s) => [s.selectedDatabase, s.selectedSource],
            (selectedDatabase: SelectedDatabase, selectedSource: DirectQuerySource | null): string => {
                if (selectedDatabase === 'hogql') {
                    return 'PostHog (HogQL)'
                }
                if (!selectedSource) {
                    // Source ID is set but source not found yet (still loading)
                    return 'Loading...'
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
    listeners(() => ({
        // Schema is already discovered when source is created, no need to load separately
    })),
    afterMount(({ actions }) => {
        // Load sources immediately when the logic mounts
        // This ensures sources are available before setSelectedDatabase is called
        actions.loadSources()
    }),
])
