import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { hogql } from '~/queries/utils'

import type { queryLogLogicType } from './queryLogLogicType'

export interface QueryLogEntry {
    query_id: string
    query: string
    query_start_time: string
    query_duration_ms: number
    status: string
    exception_code: number
    result_rows: number
}

export interface QueryLogLogicProps {
    tabId: string
}

const QUERY_LOG_PAGE_SIZE = 100

async function fetchQueryLog(userId: number, limit: number, offset: number): Promise<QueryLogEntry[]> {
    const response = await api.queryHogQL(
        hogql`
            SELECT
                query_id,
                query,
                query_start_time,
                query_duration_ms,
                status,
                exception_code,
                result_rows
            FROM query_log
            WHERE created_by = ${userId}
                AND product = 'sql_editor'
                AND event_date >= today() - INTERVAL 7 DAY
                AND query != ''
            ORDER BY query_start_time DESC
            LIMIT ${limit} OFFSET ${offset}`,
        { name: 'sql_editor_query_log' }
    )

    if (!response.results || !response.columns) {
        return []
    }

    return response.results.map((row: any[]) => {
        const entry: Record<string, any> = {}
        response.columns?.forEach((column: string, index: number) => {
            entry[column] = row[index]
        })
        return entry as QueryLogEntry
    })
}

export const queryLogLogic = kea<queryLogLogicType>([
    path(['data-warehouse', 'editor', 'output-pane-tabs', 'queryLogLogic']),
    props({} as QueryLogLogicProps),
    key((props) => props.tabId),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    actions({
        loadQueryLog: true,
        loadMoreQueryLog: true,
    }),
    loaders(({ values }) => ({
        queryLog: [
            [] as QueryLogEntry[],
            {
                loadQueryLog: async () => {
                    if (!values.user?.id) {
                        return []
                    }
                    return await fetchQueryLog(values.user.id, QUERY_LOG_PAGE_SIZE, 0)
                },
            },
        ],
        moreQueryLog: [
            [] as QueryLogEntry[],
            {
                loadMoreQueryLog: async () => {
                    if (!values.user?.id) {
                        return []
                    }
                    return await fetchQueryLog(values.user.id, QUERY_LOG_PAGE_SIZE, values.queryLog.length)
                },
            },
        ],
    })),
    reducers({
        queryLog: {
            loadMoreQueryLogSuccess: (state, { moreQueryLog }) => [...state, ...moreQueryLog],
        },
    }),
    selectors({
        // A partial page means we've reached the end; an exact multiple may have one extra (empty) fetch
        hasMore: [
            (s) => [s.queryLog],
            (queryLog: QueryLogEntry[]): boolean => queryLog.length > 0 && queryLog.length % QUERY_LOG_PAGE_SIZE === 0,
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadQueryLog()
    }),
])
