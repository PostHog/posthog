import { errorTrackingActivityDescriber } from '@posthog/products-error-tracking/frontend/errorTrackingActivityDescriber'
import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api, { ActivityLogPaginatedResponse } from 'lib/api'
import {
    ActivityLogItem,
    defaultDescriber,
    Describer,
    humanize,
    HumanizedActivityLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { ACTIVITY_PAGE_SIZE } from 'lib/constants'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { cohortActivityDescriber } from 'scenes/cohorts/activityDescriptions'
import { dataManagementActivityDescriber } from 'scenes/data-management/dataManagementDescribers'
import { dataWarehouseSavedQueryActivityDescriber } from 'scenes/data-warehouse/saved_queries/activityDescriptions'
import { flagActivityDescriber } from 'scenes/feature-flags/activityDescriptions'
import { groupActivityDescriber } from 'scenes/groups/activityDescriptions'
import { hogFunctionActivityDescriber } from 'scenes/hog-functions/misc/activityDescriptions'
import { notebookActivityDescriber } from 'scenes/notebooks/Notebook/notebookActivityDescriber'
import { personActivityDescriber } from 'scenes/persons/activityDescriptions'
import { pluginActivityDescriber } from 'scenes/pipeline/pipelinePluginActivityDescriptions'
import { insightActivityDescriber } from 'scenes/saved-insights/activityDescriptions'
import { surveyActivityDescriber } from 'scenes/surveys/surveyActivityDescriber'
import { teamActivityDescriber } from 'scenes/team-activity/teamActivityDescriber'
import { urls } from 'scenes/urls'

import { ActivityScope, PipelineNodeTab, PipelineStage, PipelineTab } from '~/types'

import type { activityLogLogicType } from './activityLogLogicType'

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
        case ActivityScope.HOG_FUNCTION:
            return hogFunctionActivityDescriber
        case ActivityScope.COHORT:
            return cohortActivityDescriber
        case ActivityScope.INSIGHT:
            return insightActivityDescriber
        case ActivityScope.PERSON:
            return personActivityDescriber
        case ActivityScope.GROUP:
            return groupActivityDescriber
        case ActivityScope.EVENT_DEFINITION:
        case ActivityScope.PROPERTY_DEFINITION:
            return dataManagementActivityDescriber
        case ActivityScope.NOTEBOOK:
            return notebookActivityDescriber
        case ActivityScope.TEAM:
            return teamActivityDescriber
        case ActivityScope.SURVEY:
            return surveyActivityDescriber
        case ActivityScope.ERROR_TRACKING_ISSUE:
            return errorTrackingActivityDescriber
        case ActivityScope.DATA_WAREHOUSE_SAVED_QUERY:
            return dataWarehouseSavedQueryActivityDescriber
        default:
            return (logActivity, asNotification) => defaultDescriber(logActivity, asNotification)
    }
}

export type ActivityLogLogicProps = {
    scope: ActivityScope | ActivityScope[]
    // if no id is provided, the list is not scoped by id and shows all activity ordered by time
    id?: number | string
}

export const activityLogLogic = kea<activityLogLogicType>([
    props({} as ActivityLogLogicProps),
    key(({ scope, id }) => `activity/${Array.isArray(scope) ? scope.join(',') : scope}/${id || 'all'}`),
    path((key) => ['lib', 'components', 'ActivityLog', 'activitylog', 'logic', key]),
    actions({
        setPage: (page: number) => ({ page }),
    }),
    loaders(({ values, props }) => ({
        activity: [
            { results: [], count: 0 } as ActivityLogPaginatedResponse<ActivityLogItem>,
            {
                fetchActivity: async () => {
                    const response = await api.activity.listLegacy(props, values.page)
                    return { results: response.results, count: (response as any).total_count ?? response.count }
                },
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
        const onPageChange = (
            searchParams: Record<string, any>,
            hashParams: Record<string, any>,
            pageScope: ActivityScope,
            forceUsePageParam?: boolean
        ): void => {
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
            [urls.pipelineNode(PipelineStage.Destination, ':id', PipelineNodeTab.History)]: (
                _,
                searchParams,
                hashParams
            ) => onPageChange(searchParams, hashParams, ActivityScope.HOG_FUNCTION),
            [urls.pipeline(PipelineTab.History)]: (_, searchParams, hashParams) =>
                onPageChange(searchParams, hashParams, ActivityScope.PLUGIN),
        }
    }),
    events(({ actions }) => ({
        afterMount: () => {
            actions.fetchActivity()
        },
    })),
])
