import { events, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { fullName } from 'lib/utils'

import { ActivityScope } from '~/types'

import type { insightHistoryLogicType } from './insightHistoryLogicType'

export interface InsightHistoryLogicProps {
    insightId: number
}

/** One saved state of the insight's query: the result of a single edit. */
export interface InsightQueryVersion {
    id?: string
    createdAt: string
    authorName: string
    email?: string | null
    isSystem: boolean
    /** SQL before this edit — the previous version, used as the diff base */
    beforeSql: string
    /** SQL as of this edit — what "Restore" brings back */
    afterSql: string
}

/** Pull the HogQL text out of an insight `query` field activity change (a DataVisualizationNode). */
export function getChangeSql(changeSide: ActivityChange['before'] | ActivityChange['after']): string | null {
    if (!changeSide || typeof changeSide !== 'object' || Array.isArray(changeSide)) {
        return null
    }
    const source = (changeSide as { source?: unknown }).source
    if (!source || typeof source !== 'object') {
        return null
    }
    const query = (source as { query?: unknown }).query
    return typeof query === 'string' && query.trim() !== '' ? query : null
}

export function getQueryChange(logItem: ActivityLogItem): ActivityChange | null {
    return (
        logItem.detail?.changes?.find(
            (change) =>
                change.field === 'query' &&
                getChangeSql(change.after) !== null &&
                // Settings-only edits (chart type, axis config) also touch the query JSON —
                // only SQL text changes count as versions, otherwise the diff has nothing to show
                getChangeSql(change.after) !== getChangeSql(change.before)
        ) ?? null
    )
}

export const insightHistoryLogic = kea<insightHistoryLogicType>([
    path(['data-warehouse', 'editor', 'output-pane-tabs', 'insightHistoryLogic']),
    props({} as InsightHistoryLogicProps),
    key((props) => props.insightId),
    loaders(({ props }) => ({
        activity: [
            [] as ActivityLogItem[],
            {
                loadActivity: async () => {
                    const response = await api.activity
                        .listRequest({
                            scope: ActivityScope.INSIGHT,
                            item_id: props.insightId,
                            page_size: 50,
                        })
                        .get()
                    return response.results ?? []
                },
            },
        ],
    })),
    selectors({
        // Newest first, only edits that changed the SQL — each one is a "version"
        versions: [
            (s) => [s.activity],
            (activity): InsightQueryVersion[] =>
                activity
                    .map((logItem): InsightQueryVersion | null => {
                        const queryChange = getQueryChange(logItem)
                        if (!queryChange) {
                            return null
                        }
                        return {
                            id: logItem.id,
                            createdAt: logItem.created_at,
                            authorName: logItem.is_system ? 'PostHog' : fullName(logItem.user),
                            email: logItem.user?.email,
                            isSystem: !!logItem.is_system,
                            beforeSql: getChangeSql(queryChange.before) ?? '',
                            afterSql: getChangeSql(queryChange.after) ?? '',
                        }
                    })
                    .filter((version): version is InsightQueryVersion => version !== null),
        ],
    }),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadActivity()
        },
    })),
])
