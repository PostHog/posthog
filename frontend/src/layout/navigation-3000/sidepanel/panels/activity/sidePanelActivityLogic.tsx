import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api, { PaginatedResponse } from 'lib/api'
import { activityLogTransforms, describerFor } from 'lib/components/ActivityLog/activityLogLogic'
import { ActivityLogItem, HumanizedActivityLogItem, humanize } from 'lib/components/ActivityLog/humanizeActivity'
import { projectLogic } from 'scenes/projectLogic'

import { ActivityScope, UserBasicType } from '~/types'

import { sidePanelStateLogic } from '../../sidePanelStateLogic'
import { SidePanelSceneContext } from '../../types'
import { sidePanelContextLogic } from '../sidePanelContextLogic'
import type { sidePanelActivityLogicType } from './sidePanelActivityLogicType'

// ActivityScope values that should not appear in dropdowns
const HIDDEN_ACTIVITY_SCOPES: ActivityScope[] = [
    ActivityScope.TAGGED_ITEM, // Handled under ActivityScope.TAG
    ActivityScope.ORGANIZATION_MEMBERSHIP, // Handled under ActivityScope.ORGANIZATION
    ActivityScope.ORGANIZATION_INVITE, // Handled under ActivityScope.ORGANIZATION
    ActivityScope.EXTERNAL_DATA_SCHEMA, // Handled under ActivityScope.EXTERNAL_DATA_SOURCE
]

const getVisibleActivityScopes = (): ActivityScope[] => {
    return Object.values(ActivityScope).filter((scope) => !HIDDEN_ACTIVITY_SCOPES.includes(scope))
}

export type ActivityFilters = {
    scope?: ActivityScope | string
    item_id?: ActivityLogItem['item_id']
    user?: UserBasicType['id']
}

export interface ChangesResponse {
    results: ActivityLogItem[]
    next: string | null
    last_read: string
}

export enum SidePanelActivityTab {
    Unread = 'unread',
    All = 'all',
    Metalytics = 'metalytics',
    Subscriptions = 'subscriptions',
}

export const sidePanelActivityLogic = kea<sidePanelActivityLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelActivityLogic']),
    connect(() => ({
        values: [sidePanelContextLogic, ['sceneSidePanelContext'], projectLogic, ['currentProjectId']],
        actions: [sidePanelStateLogic, ['openSidePanel']],
    })),
    actions({
        setActiveTab: (tab: SidePanelActivityTab) => ({ tab }),
        loadAllActivity: true,
        loadOlderActivity: true,
        maybeLoadOlderActivity: true,
        setActiveFilters: (filters: ActivityFilters | null) => ({ filters }),
        setContextFromPage: (filters: ActivityFilters | null) => ({ filters }),
    }),
    reducers({
        activeTab: [
            SidePanelActivityTab.Unread as SidePanelActivityTab,
            { persist: true },
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        activeFilters: [
            null as ActivityFilters | null,
            {
                setActiveFilters: (_, { filters }) => filters,
            },
        ],
        contextFromPage: [
            null as ActivityFilters | null,
            {
                setContextFromPage: (_, { filters }) => filters,
            },
        ],
    }),
    lazyLoaders(({ values }) => ({
        allActivityResponse: [
            null as PaginatedResponse<ActivityLogItem> | null,
            {
                loadAllActivity: async (_, breakpoint) => {
                    const filters = values.activeFilters ?? {}
                    const expandedFilters = activityLogTransforms.expandListScopes(filters)
                    const response = await api.activity.list(expandedFilters)

                    breakpoint()
                    return response
                },
                loadOlderActivity: async (_, breakpoint) => {
                    await breakpoint(1)

                    if (!values.allActivityResponse?.next) {
                        return values.allActivityResponse
                    }

                    const response = await api.get<PaginatedResponse<ActivityLogItem>>(values.allActivityResponse.next)

                    response.results = [...values.allActivityResponse.results, ...response.results]

                    return response
                },
            },
        ],
    })),

    listeners(({ values, actions }) => ({
        setActiveTab: ({ tab }) => {
            if (tab === SidePanelActivityTab.All && !values.allActivityResponseLoading) {
                actions.loadAllActivity()
            }
        },
        maybeLoadOlderActivity: () => {
            if (!values.allActivityResponseLoading && values.allActivityResponse?.next) {
                actions.loadOlderActivity()
            }
        },
        openSidePanel: ({ options }) => {
            if (options) {
                actions.setActiveTab(options as SidePanelActivityTab)
            }
        },
    })),
    selectors({
        allActivity: [
            (s) => [s.allActivityResponse],
            (allActivityResponse): HumanizedActivityLogItem[] => {
                return humanize(allActivityResponse?.results || [], describerFor, true)
            },
        ],
        allActivityHasNext: [(s) => [s.allActivityResponse], (allActivityResponse) => !!allActivityResponse?.next],
        visibleActivityScopes: [
            () => [],
            (): ActivityScope[] => {
                return getVisibleActivityScopes()
            },
        ],
    }),

    subscriptions(({ actions, values }) => ({
        sceneSidePanelContext: (sceneSidePanelContext: SidePanelSceneContext) => {
            const newFilters = sceneSidePanelContext
                ? {
                      scope: sceneSidePanelContext.activity_scope,
                      item_id: sceneSidePanelContext.activity_item_id,
                  }
                : null

            actions.setContextFromPage(newFilters)
            actions.setActiveFilters(newFilters)
        },
        activeFilters: () => {
            if (values.activeTab === SidePanelActivityTab.All) {
                actions.loadAllActivity()
            }
        },
    })),

    afterMount(({ actions, values }) => {
        const sceneSidePanelContext = values.sceneSidePanelContext
        const newFilters = sceneSidePanelContext
            ? {
                  scope: sceneSidePanelContext.activity_scope,
                  item_id: sceneSidePanelContext.activity_item_id,
              }
            : null

        actions.setContextFromPage(newFilters)
        actions.setActiveFilters(newFilters)
    }),
])
