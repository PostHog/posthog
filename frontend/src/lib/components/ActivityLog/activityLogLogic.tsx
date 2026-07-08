import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api, { ActivityLogPaginatedResponse } from 'lib/api'
import {
    ActivityLogItem,
    Describer,
    HumanizedActivityLogItem,
    defaultDescriber,
    humanize,
} from 'lib/components/ActivityLog/humanizeActivity'
import { ACTIVITY_PAGE_SIZE } from 'lib/constants'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { urls } from 'scenes/urls'

import { ActivityScope } from '~/types'

import type { activityLogLogicType } from './activityLogLogicType'

// Define which scopes should be expanded to include multiple scopes
const SCOPE_EXPANSIONS: Partial<Record<ActivityScope, ActivityScope[]>> = {
    [ActivityScope.TAG]: [ActivityScope.TAG, ActivityScope.TAGGED_ITEM],
    [ActivityScope.ORGANIZATION]: [
        ActivityScope.ORGANIZATION,
        ActivityScope.ORGANIZATION_MEMBERSHIP,
        ActivityScope.ORGANIZATION_INVITE,
    ],
    [ActivityScope.EXTERNAL_DATA_SOURCE]: [ActivityScope.EXTERNAL_DATA_SOURCE, ActivityScope.EXTERNAL_DATA_SCHEMA],
}

export const activityLogTransforms = {
    expandListLegacyScopes: (
        props: ActivityLogLogicProps
    ): {
        scope: ActivityScope | ActivityScope[]
        id?: number | string
    } => {
        let scopes = Array.isArray(props.scope) ? [...props.scope] : [props.scope]

        if (scopes.length === 1 && scopes[0] in SCOPE_EXPANSIONS) {
            const expandedScopes = SCOPE_EXPANSIONS[scopes[0]]
            if (expandedScopes) {
                scopes = expandedScopes
            }
        }

        return { scope: scopes, id: props.id }
    },

    expandListScopes: (filters: { scope?: ActivityScope | string; [key: string]: any }) => {
        if (!filters.scope) {
            return filters
        }

        const scope = filters.scope as ActivityScope
        if (scope in SCOPE_EXPANSIONS) {
            const expandedScopes = SCOPE_EXPANSIONS[scope]
            if (expandedScopes) {
                return {
                    ...filters,
                    scopes: expandedScopes,
                    scope: undefined,
                }
            }
        }

        return filters
    },
}

let loadedDescriberFor: ((logItem?: ActivityLogItem) => Describer | undefined) | null = null
let describersImport: Promise<void> | null = null

/**
 * The describer registry statically imports every product's describer — a large graph
 * (insight cards, chart.js, validators) that must stay out of the eagerly-loaded app shell,
 * so it is loaded on demand here. Loaders that fetch activity items await this before
 * returning, which guarantees `describerFor` resolves real describers by the time any
 * selector humanizes those items.
 *
 * Never rejects: if the chunk fails to load (e.g. a stale tab after a deploy), the loader
 * still resolves and `describerFor` degrades to `defaultDescriber`; the next call retries.
 */
export function ensureActivityDescribersLoaded(): Promise<void> {
    describersImport ??= import('./describers')
        .then((registry) => {
            loadedDescriberFor = registry.describerFor
        })
        .catch((error) => {
            describersImport = null
            console.error('Failed to load activity describers, falling back to default descriptions', error)
        })
    return describersImport
}

/**
 * Having this function inside the `humanizeActivity module was causing very weird test errors in other modules
 * see https://github.com/PostHog/posthog/pull/12062
 * So, we inject the function instead
 * **/
export const describerFor = (logItem?: ActivityLogItem): Describer | undefined => {
    if (!loadedDescriberFor) {
        void ensureActivityDescribersLoaded()
        return defaultDescriber
    }
    return loadedDescriberFor(logItem)
}

export type ActivityLogLogicProps = {
    scope: ActivityScope | ActivityScope[]
    // if no id is provided, the list is not scoped by id and shows all activity ordered by time
    id?: number | string
    // page to load on mount (callers that deep-link into a paginated activity feed)
    startingPage?: number
}

export const activityLogLogic = kea<activityLogLogicType>([
    props({} as ActivityLogLogicProps),
    key(({ scope, id }) => `activity/${Array.isArray(scope) ? scope.join(',') : scope}/${id || 'all'}`),
    path((key) => ['lib', 'components', 'ActivityLog', 'activitylog', 'logic', key]),
    actions({
        setPage: (page: number) => ({ page }),
        setHighlightedActivityId: (id: string | null) => ({ id }),
    }),
    loaders(({ values, props }) => ({
        activity: [
            { results: [], count: 0 } as ActivityLogPaginatedResponse<ActivityLogItem>,
            {
                fetchActivity: async () => {
                    const transformedProps = activityLogTransforms.expandListLegacyScopes(props)
                    const [response] = await Promise.all([
                        api.activity.listLegacy(transformedProps, values.page),
                        ensureActivityDescribersLoaded(),
                    ])
                    return { results: response.results, count: (response as any).total_count ?? response.count }
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        page: [
            props.startingPage ?? 1,
            {
                setPage: (_, { page }) => page,
            },
        ],
        highlightedActivityId: [
            null as string | null,
            {
                setHighlightedActivityId: (_, { id }) => id,
            },
        ],
    })),
    selectors(({ actions }) => ({
        pagination: [
            (s) => [s.page, s.totalCount],
            (page, totalCount): PaginationManual => {
                return {
                    controlled: true,
                    pageSize: ACTIVITY_PAGE_SIZE,
                    currentPage: page,
                    entryCount: totalCount || 0,
                    onBackward: () => actions.setPage(page - 1),
                    onForward: () => actions.setPage(page + 1),
                }
            },
        ],
        humanizedActivity: [
            (s) => [s.activity],
            (activity): HumanizedActivityLogItem[] => {
                return activity.results ? humanize(activity.results, describerFor) : []
            },
        ],
        totalCount: [
            (s) => [s.activity],
            (activity): number | null => {
                return activity.count ?? null
            },
        ],
    })),
    listeners(({ actions }) => ({
        setPage: async (_, breakpoint) => {
            breakpoint()
            actions.fetchActivity()
        },
    })),
    urlToAction(({ values, actions, props }) => {
        const syncActivityHighlight = (searchParams: Record<string, any>): void => {
            const activityId = searchParams?.activity
            if (activityId && activityId !== values.highlightedActivityId) {
                actions.setHighlightedActivityId(activityId)
            } else if (!activityId && values.highlightedActivityId !== null) {
                actions.setHighlightedActivityId(null)
            }
        }

        const onPageChange = (
            searchParams: Record<string, any>,
            hashParams: Record<string, any>,
            pageScope: ActivityScope,
            forceUsePageParam?: boolean
        ): void => {
            syncActivityHighlight(searchParams)

            const pageInURL = searchParams['page']
            const firstScope = Array.isArray(props.scope) ? props.scope[0] : props.scope

            const shouldPage =
                forceUsePageParam ||
                (pageScope === ActivityScope.PERSON && hashParams['activeTab'] === 'history') ||
                ([ActivityScope.FEATURE_FLAG, ActivityScope.INSIGHT, ActivityScope.PLUGIN].includes(pageScope) &&
                    searchParams['tab'] === 'history')

            if (shouldPage && pageInURL && pageInURL !== values.page && pageScope === firstScope) {
                actions.setPage(pageInURL)
            }

            const shouldRemovePageParam =
                (pageScope === ActivityScope.PERSON && hashParams['activeTab'] !== 'history') ||
                ([ActivityScope.FEATURE_FLAG, ActivityScope.INSIGHT, ActivityScope.PLUGIN].includes(pageScope) &&
                    searchParams['tab'] !== 'history')

            if (!forceUsePageParam && shouldRemovePageParam && 'page' in router.values.searchParams) {
                const { page: _, ...newSearchParams } = router.values.searchParams
                router.actions.replace(
                    router.values.currentLocation.pathname,
                    newSearchParams,
                    router.values.hashParams
                )
            }
        }
        return {
            '/person/*': (_, searchParams, hashParams) => onPageChange(searchParams, hashParams, ActivityScope.PERSON),
            [urls.featureFlags()]: (_, searchParams, hashParams) =>
                onPageChange(searchParams, hashParams, ActivityScope.FEATURE_FLAG),
            [urls.savedInsights()]: (_, searchParams, hashParams) =>
                onPageChange(searchParams, hashParams, ActivityScope.INSIGHT),
            [urls.featureFlag(':id')]: (_, searchParams, hashParams) =>
                onPageChange(searchParams, hashParams, ActivityScope.FEATURE_FLAG, true),
            // Catch-all for pages that don't need pagination handling (surveys, product
            // tours, experiments, etc.) but still support ?activity= deep linking.
            '*': (_, searchParams) => syncActivityHighlight(searchParams),
        }
    }),
    events(({ actions, values }) => ({
        afterMount: () => {
            if (!values.activity.results.length && !values.activityLoading) {
                actions.fetchActivity()
            }
        },
    })),
])
