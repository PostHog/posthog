import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { ActivityDescriber as errorTrackingActivityDescriber } from '@posthog/products-error-tracking/frontend/components/ActivityDescriber'

import api, { ActivityLogPaginatedResponse } from 'lib/api'
import { tagActivityDescriber } from 'lib/components/ActivityLog/activityDescriptions/tagActivityDescriber'
import {
    ActivityLogItem,
    Describer,
    HumanizedActivityLogItem,
    defaultDescriber,
    humanize,
} from 'lib/components/ActivityLog/humanizeActivity'
import { ACTIVITY_PAGE_SIZE } from 'lib/constants'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { actionActivityDescriber } from 'scenes/actions/actionActivityDescriber'
import { alertConfigurationActivityDescriber } from 'scenes/alerts/activityDescriptions'
import { annotationActivityDescriber } from 'scenes/annotations/activityDescriptions'
import { userActivityDescriber } from 'scenes/authentication/activityDescriptions'
import { cohortActivityDescriber } from 'scenes/cohorts/activityDescriptions'
import { dashboardActivityDescriber } from 'scenes/dashboard/dashboardActivityDescriber'
import { dataManagementActivityDescriber } from 'scenes/data-management/dataManagementDescribers'
import { batchExportActivityDescriber } from 'scenes/data-pipelines/batch-exports/activityDescriptions'
import { batchImportActivityDescriber } from 'scenes/data-pipelines/batch-imports/activityDescriptions'
import { externalDataSourceActivityDescriber } from 'scenes/data-warehouse/external-data-sources/activityDescriptions'
import { dataWarehouseSavedQueryActivityDescriber } from 'scenes/data-warehouse/saved_queries/activityDescriptions'
import { experimentActivityDescriber } from 'scenes/experiments/experimentActivityDescriber'
import { flagActivityDescriber } from 'scenes/feature-flags/activityDescriptions'
import { groupActivityDescriber } from 'scenes/groups/activityDescriptions'
import { hogFunctionActivityDescriber } from 'scenes/hog-functions/misc/activityDescriptions'
import { notebookActivityDescriber } from 'scenes/notebooks/Notebook/notebookActivityDescriber'
import { personActivityDescriber } from 'scenes/persons/activityDescriptions'
import { insightActivityDescriber } from 'scenes/saved-insights/activityDescriptions'
import { replayActivityDescriber } from 'scenes/session-recordings/activityDescription'
import { organizationActivityDescriber } from 'scenes/settings/organization/activityDescriptions'
import { personalAPIKeyActivityDescriber } from 'scenes/settings/user/activityDescriptions'
import { surveyActivityDescriber } from 'scenes/surveys/surveyActivityDescriber'
import { teamActivityDescriber } from 'scenes/team-activity/teamActivityDescriber'
import { urls } from 'scenes/urls'

import { ActivityScope } from '~/types'

import { workflowActivityDescriber } from 'products/workflows/frontend/Workflows/misc/workflowActivityDescriber'

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

/**
 * Having this function inside the `humanizeActivity module was causing very weird test errors in other modules
 * see https://github.com/PostHog/posthog/pull/12062
 * So, we inject the function instead
 * **/
export const describerFor = (logItem?: ActivityLogItem): Describer | undefined => {
    switch (logItem?.scope) {
        case ActivityScope.ACTION:
            return actionActivityDescriber
        case ActivityScope.ALERT_CONFIGURATION:
            return alertConfigurationActivityDescriber
        case ActivityScope.ANNOTATION:
            return annotationActivityDescriber
        case ActivityScope.BATCH_EXPORT:
            return batchExportActivityDescriber
        case ActivityScope.BATCH_IMPORT:
            return batchImportActivityDescriber
        case ActivityScope.DASHBOARD:
            return dashboardActivityDescriber
        case ActivityScope.FEATURE_FLAG:
            return flagActivityDescriber
        case ActivityScope.HOG_FUNCTION:
            return hogFunctionActivityDescriber
        case ActivityScope.HOG_FLOW:
            return workflowActivityDescriber
        case ActivityScope.COHORT:
            return cohortActivityDescriber
        case ActivityScope.INSIGHT:
            return insightActivityDescriber
        case ActivityScope.DASHBOARD:
            return dashboardActivityDescriber
        case ActivityScope.PERSON:
            return personActivityDescriber
        case ActivityScope.PERSONAL_API_KEY:
            return personalAPIKeyActivityDescriber
        case ActivityScope.GROUP:
            return groupActivityDescriber
        case ActivityScope.EVENT_DEFINITION:
        case ActivityScope.PROPERTY_DEFINITION:
            return dataManagementActivityDescriber
        case ActivityScope.NOTEBOOK:
            return notebookActivityDescriber
        case ActivityScope.TEAM:
            return teamActivityDescriber
        case ActivityScope.ORGANIZATION:
        case ActivityScope.ORGANIZATION_MEMBERSHIP:
        case ActivityScope.ORGANIZATION_INVITE:
            return organizationActivityDescriber
        case ActivityScope.SURVEY:
            return surveyActivityDescriber
        case ActivityScope.ERROR_TRACKING_ISSUE:
            return errorTrackingActivityDescriber
        case ActivityScope.DATA_WAREHOUSE_SAVED_QUERY:
            return dataWarehouseSavedQueryActivityDescriber
        case ActivityScope.REPLAY:
            return replayActivityDescriber
        case ActivityScope.HEATMAP:
            return (logActivity, asNotification) => defaultDescriber(logActivity, asNotification)
        case ActivityScope.EXPERIMENT:
            return experimentActivityDescriber
        case ActivityScope.TAG:
        case ActivityScope.TAGGED_ITEM:
            return tagActivityDescriber
        case ActivityScope.EXTERNAL_DATA_SOURCE:
        case ActivityScope.EXTERNAL_DATA_SCHEMA:
            return externalDataSourceActivityDescriber
        case ActivityScope.USER:
            return userActivityDescriber
        case ActivityScope.ENDPOINT:
            return (logActivity, asNotification) => defaultDescriber(logActivity, asNotification)
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
                    const transformedProps = activityLogTransforms.expandListLegacyScopes(props)
                    const response = await api.activity.listLegacy(transformedProps, values.page)
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
            [urls.dataPipelines('history')]: (_, searchParams, hashParams) =>
                onPageChange(searchParams, hashParams, ActivityScope.PLUGIN),
        }
    }),
    events(({ actions }) => ({
        afterMount: () => {
            actions.fetchActivity()
        },
    })),
])
