import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { HogQLQueryResponse } from '~/queries/schema/schema-general'

import type { queryLogTableLogicType } from './queryLogTableLogicType'

export interface QueryLogEntry {
    query_id: string
    query: string
    query_start_time: string
    query_duration_ms: number
    name: string
    status: string
    exception_code: number
    read_rows: number
    read_bytes: number
    result_rows: number
}

export interface QueryLogTableLogicProps {
    key: string
    product?: string
}

export const queryLogTableLogic = kea<queryLogTableLogicType>([
    path(['scenes', 'debug', 'queryLogTableLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    actions({
        loadQueryLogs: true,
        loadMoreQueryLogs: true,
    }),
    loaders(({ values, props }) => ({
        queryLogs: [
            [] as QueryLogEntry[],
            {
                loadQueryLogs: async () => {
                    try {
                        if (!values.user?.id) {
                            return []
                        }
                        const productFilter = props.product ? `AND product = {product}` : ''
                        const response = (await api.query({
                            kind: 'HogQLQuery',
                            query: `
                                SELECT
                                    query_id,
                                    query,
                                    query_start_time,
                                    query_duration_ms,
                                    name,
                                    status,
                                    exception_code,
                                    read_rows,
                                    read_bytes,
                                    result_rows
                                FROM query_log
                                WHERE created_by = {user_id}
                                    AND event_date >= today() - INTERVAL 7 DAY
                                    AND query != ''
                                    ${productFilter}
                                ORDER BY query_start_time DESC
                                LIMIT {limit}
                            `,
                            values: {
                                user_id: values.user.id,
                                limit: values.limit,
                                ...(props.product ? { product: props.product } : {}),
                            },
                        })) as HogQLQueryResponse

                        // Convert array of arrays to array of objects
                        if (!response.results || !response.columns) {
                            return []
                        }

                        return response.results.map((row: any[]) => {
                            const obj: any = {}
                            response.columns!.forEach((col: string, idx: number) => {
                                obj[col] = row[idx]
                            })
                            return obj as QueryLogEntry
                        })
                    } catch (error) {
                        console.error('Error loading query logs:', error)
                        return []
                    }
                },
            },
        ],
        moreQueryLogs: [
            [] as QueryLogEntry[],
            {
                loadMoreQueryLogs: async () => {
                    try {
                        if (!values.user?.id) {
                            return []
                        }
                        const productFilter = props.product ? `AND product = {product}` : ''
                        const response = (await api.query({
                            kind: 'HogQLQuery',
                            query: `
                                SELECT
                                    query_id,
                                    query,
                                    query_start_time,
                                    query_duration_ms,
                                    name,
                                    status,
                                    exception_code,
                                    read_rows,
                                    read_bytes,
                                    result_rows
                                FROM query_log
                                WHERE created_by = {user_id}
                                    AND event_date >= today() - INTERVAL 7 DAY
                                    AND query != ''
                                    ${productFilter}
                                ORDER BY query_start_time DESC
                                LIMIT {limit} OFFSET {offset}
                            `,
                            values: {
                                user_id: values.user.id,
                                limit: values.limit,
                                offset: values.queryLogs.length,
                                ...(props.product ? { product: props.product } : {}),
                            },
                        })) as HogQLQueryResponse

                        // Convert array of arrays to array of objects
                        if (!response.results || !response.columns) {
                            return []
                        }

                        return response.results.map((row: any[]) => {
                            const obj: any = {}
                            response.columns!.forEach((col: string, idx: number) => {
                                obj[col] = row[idx]
                            })
                            return obj as QueryLogEntry
                        })
                    } catch (error) {
                        console.error('Error loading more query logs:', error)
                        return []
                    }
                },
            },
        ],
    })),
    reducers({
        limit: [100, {}],
        queryLogs: {
            loadQueryLogsSuccess: (_, { queryLogs }) => queryLogs,
            loadMoreQueryLogsSuccess: (state, { moreQueryLogs }) => [...state, ...moreQueryLogs],
        },
    }),
    selectors({
        queryLogsWithIndex: [
            (s) => [s.queryLogs],
            (queryLogs: QueryLogEntry[]): (QueryLogEntry & { index: number })[] =>
                queryLogs.map((log, index) => ({ ...log, index })),
        ],
        hasMore: [
            (s) => [s.moreQueryLogs, s.limit],
            (moreQueryLogs: QueryLogEntry[], limit: number): boolean => moreQueryLogs.length === limit,
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadQueryLogs()
    }),
])
