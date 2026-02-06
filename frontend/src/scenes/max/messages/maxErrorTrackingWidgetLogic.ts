import { actions, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { performQuery } from '~/queries/query'
import {
    MaxErrorTrackingIssuePreview,
    MaxErrorTrackingSearchResponse,
} from '~/queries/schema/schema-assistant-error-tracking'
import { ErrorTrackingQuery, NodeKind } from '~/queries/schema/schema-general'

import type { maxErrorTrackingWidgetLogicType } from './maxErrorTrackingWidgetLogicType'

export interface MaxErrorTrackingWidgetLogicProps {
    toolCallId: string
    filters: MaxErrorTrackingSearchResponse | null | undefined
}

export const maxErrorTrackingWidgetLogic = kea<maxErrorTrackingWidgetLogicType>([
    path(['scenes', 'max', 'messages', 'maxErrorTrackingWidgetLogic']),
    props({} as MaxErrorTrackingWidgetLogicProps),
    key((props) => props.toolCallId),

    actions({
        loadMoreIssues: true,
    }),

    reducers(({ props }) => ({
        issues: [
            (props.filters?.issues ?? []) as MaxErrorTrackingIssuePreview[],
            {
                loadMoreIssuesSuccess: (state, { moreIssuesResponse }) =>
                    moreIssuesResponse ? [...state, ...moreIssuesResponse.issues] : state,
            },
        ],
        hasMore: [
            props.filters?.has_more ?? false,
            {
                loadMoreIssuesSuccess: (_, { moreIssuesResponse }) => moreIssuesResponse?.hasMore ?? false,
            },
        ],
        nextCursor: [
            (props.filters?.next_cursor ?? null) as string | null,
            {
                loadMoreIssuesSuccess: (_, { moreIssuesResponse }) => moreIssuesResponse?.nextCursor ?? null,
            },
        ],
    })),

    loaders(({ props, values }) => ({
        moreIssuesResponse: [
            null as { issues: MaxErrorTrackingIssuePreview[]; hasMore: boolean; nextCursor: string | null } | null,
            {
                loadMoreIssues: async () => {
                    const filters = props.filters
                    if (!filters) {
                        return null
                    }
                    const currentOffset = values.nextCursor ? parseInt(values.nextCursor, 10) : values.issues.length
                    const limit = filters.limit ?? 50

                    const query: ErrorTrackingQuery = {
                        kind: NodeKind.ErrorTrackingQuery,
                        status: (filters.status ?? undefined) as ErrorTrackingQuery['status'],
                        searchQuery: filters.search_query ?? undefined,
                        dateRange: {
                            date_from: filters.date_from ?? undefined,
                            date_to: filters.date_to ?? undefined,
                        },
                        orderBy: (filters.order_by ?? 'last_seen') as ErrorTrackingQuery['orderBy'],
                        orderDirection: (filters.order_direction ?? 'DESC') as ErrorTrackingQuery['orderDirection'],
                        limit: limit,
                        offset: currentOffset,
                        withAggregations: true,
                        withFirstEvent: false,
                        filterTestAccounts: false,
                        volumeResolution: 1,
                    }

                    const response = await performQuery(query)
                    const results = (response.results ?? []) as any[]

                    const newIssues: MaxErrorTrackingIssuePreview[] = results.map((issue) => ({
                        id: issue.id,
                        name: issue.name,
                        description: issue.description,
                        status: issue.status,
                        library: issue.library,
                        first_seen: issue.first_seen,
                        last_seen: issue.last_seen,
                        occurrences: issue.aggregations?.occurrences ?? 0,
                        users: issue.aggregations?.users ?? 0,
                        sessions: issue.aggregations?.sessions ?? 0,
                    }))

                    const hasMore = response.hasMore ?? results.length >= limit
                    const newNextCursor = hasMore ? String(currentOffset + limit) : null

                    return { issues: newIssues, hasMore, nextCursor: newNextCursor }
                },
            },
        ],
    })),

    selectors({
        isLoading: [(s) => [s.moreIssuesResponseLoading], (loading: boolean) => loading],
    }),
])
