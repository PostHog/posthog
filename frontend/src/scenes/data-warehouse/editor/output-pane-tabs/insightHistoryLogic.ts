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

const ACTIVITY_PAGE_SIZE = 100
// Safety cap: 10 pages = 1000 activity entries. Beyond that we stop and admit the history is partial.
const ACTIVITY_MAX_PAGES = 10

export interface InsightActivityPage {
    items: ActivityLogItem[]
    /** False when the log was too long to fetch fully — the oldest loaded entry is NOT the creation state */
    complete: boolean
}

export const insightHistoryLogic = kea<insightHistoryLogicType>([
    path(['data-warehouse', 'editor', 'output-pane-tabs', 'insightHistoryLogic']),
    props({} as InsightHistoryLogicProps),
    key((props) => props.insightId),
    loaders(({ props }) => ({
        activityPage: [
            { items: [], complete: true } as InsightActivityPage,
            {
                loadActivity: async () => {
                    const items: ActivityLogItem[] = []
                    for (let page = 1; page <= ACTIVITY_MAX_PAGES; page++) {
                        const response = await api.activity
                            .listRequest({
                                scope: ActivityScope.INSIGHT,
                                item_id: props.insightId,
                                page,
                                page_size: ACTIVITY_PAGE_SIZE,
                            })
                            .get()
                        const results = response.results ?? []
                        items.push(...results)
                        if (results.length < ACTIVITY_PAGE_SIZE) {
                            return { items, complete: true }
                        }
                    }
                    return { items, complete: false }
                },
            },
        ],
    })),
    selectors({
        activity: [(s) => [s.activityPage], (activityPage) => activityPage.items],
        historyComplete: [(s) => [s.activityPage], (activityPage) => activityPage.complete],
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
