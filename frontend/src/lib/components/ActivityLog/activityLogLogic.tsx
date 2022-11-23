import { kea } from 'kea'
import api, { ACTIVITY_PAGE_SIZE, CountedPaginatedResponse } from 'lib/api'
import {
    ActivityLogItem,
    ActivityScope,
    Describer,
    humanize,
    HumanizedActivityLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { ActivityLogProps } from 'lib/components/ActivityLog/ActivityLog'

import type { activityLogLogicType } from './activityLogLogicType'
import { PaginationManual } from 'lib/components/PaginationControl'
import { urls } from 'scenes/urls'
import { router } from 'kea-router'
import { flagActivityDescriber } from 'scenes/feature-flags/activityDescriptions'
import { pluginActivityDescriber } from 'scenes/plugins/pluginActivityDescriptions'
import { insightActivityDescriber } from 'scenes/saved-insights/activityDescriptions'
import { personActivityDescriber } from 'scenes/persons/activityDescriptions'

/**
 * Having this function inside the `humanizeActivity module was causing very weird test errors in other modules
 * see https://github.com/PostHog/posthog/pull/12062
 * So, we inject the function instead
 * **/
export const describerFor = (logItem?: ActivityLogItem): Describer | undefined => {
    switch (logItem?.scope) {
        case ActivityScope.FEATURE_FLAG:
            return flagActivityDescriber
        case ActivityScope.PLUGIN:
        case ActivityScope.PLUGIN_CONFIG:
            return pluginActivityDescriber
        case ActivityScope.INSIGHT:
            return insightActivityDescriber
        case ActivityScope.PERSON:
            return personActivityDescriber
        default:
            return undefined
    }
}

export const activityLogLogic = kea<activityLogLogicType>({
    path: (key) => ['lib', 'components', 'ActivityLog', 'activitylog', 'logic', key],
    props: {} as ActivityLogProps,
    key: ({ scope, id }) => `activity/${scope}/${id || 'all'}`,
    actions: {
        setPage: (page: number) => ({ page }),
    },
    loaders: ({ values, props }) => ({
        nextPage: [
            { results: [], total_count: 0 } as CountedPaginatedResponse<ActivityLogItem>,
            {
                fetchNextPage: async () => await api.activity.list(props, values.page),
            },
        ],
        previousPage: [
            { results: [], total_count: 0 } as CountedPaginatedResponse<ActivityLogItem>,
            {
                fetchPreviousPage: async () => await api.activity.list(props, values.page - 1),
            },
        ],
    }),
    reducers: () => ({
        page: [
            1,
            {
                setPage: (_, { page }) => page,
            },
        ],
        humanizedActivity: [
            [] as HumanizedActivityLogItem[],
            {
                fetchNextPageSuccess: (state, { nextPage }) =>
                    nextPage ? humanize(nextPage.results, describerFor) : state,
                fetchPreviousPageSuccess: (state, { previousPage }) =>
                    previousPage ? humanize(previousPage.results, describerFor) : state,
            },
        ],
        totalCount: [
            null as number | null,
            {
                fetchNextPageSuccess: (_, { nextPage }) => nextPage.total_count || null,
                fetchPreviousPageSuccess: (_, { previousPage }) => previousPage.total_count || null,
            },
        ],
    }),
    selectors: ({ actions }) => ({
        pagination: [
            (s) => [s.page, s.totalCount],
            (page, totalCount): PaginationManual => {
                return {
                    controlled: true,
                    pageSize: ACTIVITY_PAGE_SIZE,
                    currentPage: page,
                    entryCount: totalCount || 0,
                    onBackward: actions.fetchPreviousPage,
                    onForward: actions.fetchNextPage,
                }
            },
        ],
    }),
    listeners: ({ actions }) => ({
        setPage: async (_, breakpoint) => {
            await breakpoint()
            actions.fetchNextPage()
        },
    }),
    urlToAction: ({ values, actions, props }) => {
        const onPageChange = (
            searchParams: Record<string, any>,
            hashParams: Record<string, any>,
            pageScope: ActivityScope,
            forceUsePageParam?: boolean
        ): void => {
            const pageInURL = searchParams['page']

            const shouldPage =
                forceUsePageParam ||
                (pageScope === ActivityScope.PERSON && hashParams['activeTab'] === 'history') ||
                ([ActivityScope.FEATURE_FLAG, ActivityScope.INSIGHT, ActivityScope.PLUGIN].includes(pageScope) &&
                    searchParams['tab'] === 'history')

            if (shouldPage && pageInURL && pageInURL !== values.page && pageScope === props.scope) {
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
            '/person/*': ({}, searchParams, hashParams) => onPageChange(searchParams, hashParams, ActivityScope.PERSON),
            [urls.featureFlags()]: ({}, searchParams, hashParams) =>
                onPageChange(searchParams, hashParams, ActivityScope.FEATURE_FLAG),
            [urls.savedInsights()]: ({}, searchParams, hashParams) =>
                onPageChange(searchParams, hashParams, ActivityScope.INSIGHT),
            [urls.projectApps()]: ({}, searchParams, hashParams) =>
                onPageChange(searchParams, hashParams, ActivityScope.PLUGIN),
            [urls.featureFlag(':id')]: ({}, searchParams, hashParams) =>
                onPageChange(searchParams, hashParams, ActivityScope.FEATURE_FLAG, true),
            [urls.appHistory(':pluginConfigId')]: ({}, searchParams, hashParams) =>
                onPageChange(searchParams, hashParams, ActivityScope.PLUGIN, true),
        }
    },
    events: ({ actions }) => ({
        afterMount: () => {
            actions.fetchNextPage()
        },
    }),
})
