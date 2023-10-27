import { loaders } from 'kea-loaders'
import { kea, props, key, path, actions, reducers, selectors, listeners, events } from 'kea'
import api, { ACTIVITY_PAGE_SIZE, ActivityLogPaginatedResponse } from 'lib/api'
import {
    ActivityLogItem,
    ActivityScope,
    Describer,
    humanize,
    HumanizedActivityLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

import type { activityLogLogicType } from './activityLogLogicType'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { urls } from 'scenes/urls'
import { router, urlToAction } from 'kea-router'
import { flagActivityDescriber } from 'scenes/feature-flags/activityDescriptions'
import { pluginActivityDescriber } from 'scenes/plugins/pluginActivityDescriptions'
import { insightActivityDescriber } from 'scenes/saved-insights/activityDescriptions'
import { personActivityDescriber } from 'scenes/persons/activityDescriptions'
import { dataManagementActivityDescriber } from 'scenes/data-management/dataManagementDescribers'
import { notebookActivityDescriber } from 'scenes/notebooks/Notebook/notebookActivityDescriber'

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
        case ActivityScope.EVENT_DEFINITION:
        case ActivityScope.PROPERTY_DEFINITION:
            return dataManagementActivityDescriber
        case ActivityScope.NOTEBOOK:
            return notebookActivityDescriber
        default:
            return undefined
    }
}

export type ActivityLogLogicProps = {
    scope: ActivityScope
    // if no id is provided, the list is not scoped by id and shows all activity ordered by time
    id?: number | string
}

export const activityLogLogic = kea<activityLogLogicType>([
    props({} as ActivityLogLogicProps),
    key(({ scope, id }) => `activity/${scope}/${id || 'all'}`),
    path((key) => ['lib', 'components', 'ActivityLog', 'activitylog', 'logic', key]),
    actions({
        setPage: (page: number) => ({ page }),
    }),
    loaders(({ values, props }) => ({
        activity: [
            { results: [], total_count: 0 } as ActivityLogPaginatedResponse<ActivityLogItem>,
            {
                fetchActivity: async () => await api.activity.list(props, values.page),
            },
        ],
    })),
    reducers(() => ({
        page: [
            1,
            {
                setPage: (_, { page }) => page,
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
                return activity.total_count ?? null
            },
        ],
    })),
    listeners(({ actions }) => ({
        setPage: async (_, breakpoint) => {
            await breakpoint()
            actions.fetchActivity()
        },
    })),
    urlToAction(({ values, actions, props }) => {
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
            '/person/*': (_, searchParams, hashParams) => onPageChange(searchParams, hashParams, ActivityScope.PERSON),
            [urls.featureFlags()]: (_, searchParams, hashParams) =>
                onPageChange(searchParams, hashParams, ActivityScope.FEATURE_FLAG),
            [urls.savedInsights()]: (_, searchParams, hashParams) =>
                onPageChange(searchParams, hashParams, ActivityScope.INSIGHT),
            [urls.projectApps()]: (_, searchParams, hashParams) =>
                onPageChange(searchParams, hashParams, ActivityScope.PLUGIN),
            [urls.featureFlag(':id')]: (_, searchParams, hashParams) =>
                onPageChange(searchParams, hashParams, ActivityScope.FEATURE_FLAG, true),
            [urls.appHistory(':pluginConfigId')]: (_, searchParams, hashParams) =>
                onPageChange(searchParams, hashParams, ActivityScope.PLUGIN, true),
        }
    }),
    events(({ actions }) => ({
        afterMount: () => {
            actions.fetchActivity()
        },
    })),
])
