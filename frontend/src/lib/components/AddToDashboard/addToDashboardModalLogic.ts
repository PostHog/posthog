import FuseClass from 'fuse.js'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightsApi } from 'scenes/insights/utils/api'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardBasicType, DashboardType, InsightLogicProps } from '~/types'

import type { addToDashboardModalLogicType } from './addToDashboardModalLogicType'

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<any> {}

export const addToDashboardModalLogic = kea<addToDashboardModalLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['lib', 'components', 'AddToDashboard', 'saveToDashboardModalLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [insightLogic(props), ['insight']],
        actions: [
            insightLogic(props),
            ['updateInsight', 'updateInsightSuccess', 'updateInsightFailure'],
            eventUsageLogic,
            ['reportSavedInsightToDashboard', 'reportRemovedInsightFromDashboard', 'reportCreatedDashboardFromModal'],
            newDashboardLogic,
            ['showNewDashboardModal'],
        ],
    })),
    actions({
        addNewDashboard: true,
        setSearchQuery: (query: string) => ({ query }),
        setScrollIndex: (index: number) => ({ index }),
        addToDashboard: (dashboardId: number) => ({ dashboardId }),
        removeFromDashboard: (dashboardId: number) => ({ dashboardId }),
        setDashboardToNavigateTo: (dashboardId: number | null) => ({ dashboardId }),
        setDashboardWithActiveAPICall: (dashboardId: number | null) => ({ dashboardId }),
    }),
    reducers({
        searchQuery: ['', { setSearchQuery: (_, { query }) => query }],
        scrollIndex: [-1 as number, { setScrollIndex: (_, { index }) => index }],
        dashboardWithActiveAPICall: [
            null as number | null,
            {
                addToDashboard: (_, { dashboardId }) => dashboardId,
                removeFromDashboard: (_, { dashboardId }) => dashboardId,
                setDashboardWithActiveAPICall: (_, { dashboardId }) => dashboardId,
                updateInsightSuccess: () => null,
                updateInsightFailure: () => null,
            },
        ],
        _dashboardToNavigateTo: [
            null as number | null,
            {
                setDashboardToNavigateTo: (_, { dashboardId }) => dashboardId,
            },
        ],
    }),
    selectors({
        dashboardsFuse: [
            () => [dashboardsModel.selectors.nameSortedDashboards],
            (nameSortedDashboards): Fuse => {
                return new FuseClass(nameSortedDashboards || [], {
                    keys: ['name', 'description', 'tags'],
                    threshold: 0.3,
                })
            },
        ],
        filteredDashboards: [
            (s) => [s.searchQuery, s.dashboardsFuse, dashboardsModel.selectors.nameSortedDashboards],
            (searchQuery, dashboardsFuse, nameSortedDashboards): DashboardBasicType[] =>
                searchQuery.length
                    ? dashboardsFuse.search(searchQuery).map((r: FuseClass.FuseResult<DashboardType>) => r.item)
                    : nameSortedDashboards,
        ],
        currentDashboards: [
            (s) => [s.filteredDashboards, s.insight],
            (filteredDashboards, insight): DashboardBasicType[] =>
                filteredDashboards.filter((d) => insight.dashboard_tiles?.map((dt) => dt.dashboard_id)?.includes(d.id)),
        ],
        availableDashboards: [
            (s) => [s.filteredDashboards, s.currentDashboards],
            (filteredDashboards, currentDashboards): DashboardBasicType[] =>
                filteredDashboards.filter((d) => !currentDashboards?.map((cd) => cd.id).includes(d.id)),
        ],
        orderedDashboards: [
            (s) => [s.currentDashboards, s.availableDashboards],
            (currentDashboards, availableDashboards): DashboardBasicType[] => [
                ...currentDashboards,
                ...availableDashboards,
            ],
        ],
    }),
    listeners(({ actions, values }) => ({
        addNewDashboard: async () => {
            actions.showNewDashboardModal()
            newDashboardLogic.actions.setRedirectAfterCreation(false)
        },

        [dashboardsModel.actionTypes.addDashboardSuccess]: async ({ dashboard }) => {
            actions.reportCreatedDashboardFromModal()
            // Navigate to the new dashboard immediately, before the updateInsight
            // API call. The dashboard is already created at this point. We can't
            // wait for updateInsight because it goes through insightLogic's shared
            // loader, which can be cancelled by concurrent loadInsight calls
            // triggered by the hideNewDashboardModal URL hash change.
            actions.setDashboardToNavigateTo(dashboard.id)
            actions.addToDashboard(dashboard.id)
            actions.setScrollIndex(values.orderedDashboards.findIndex((d) => d.id === dashboard.id))
        },

        addToDashboard: async ({ dashboardId }) => {
            const shouldNavigate = values._dashboardToNavigateTo === dashboardId

            // Navigate immediately if this is a "create new dashboard" flow.
            // Don't wait for the PATCH call — it can be cancelled by concurrent
            // loadInsight actions on the shared Kea loader (race condition).
            if (shouldNavigate) {
                actions.setDashboardToNavigateTo(null)
                router.actions.push(urls.dashboard(dashboardId))
            }

            // Update the insight's dashboards list via direct API call instead
            // of insightLogic's updateInsight loader, to avoid cancellation by
            // concurrent loadInsight calls on the same loader.
            try {
                const insightId = values.insight.id
                if (insightId) {
                    await insightsApi.update(insightId as number, {
                        dashboards: [...(values.insight.dashboards || []), dashboardId],
                    })
                }
                actions.reportSavedInsightToDashboard(values.insight, dashboardId)
                dashboardsModel.actions.tileAddedToDashboard(dashboardId)
                if (!shouldNavigate) {
                    lemonToast.success('Insight added to dashboard', {
                        button: {
                            label: 'View dashboard',
                            action: () => router.actions.push(urls.dashboard(dashboardId)),
                        },
                    })
                }
            } catch (e) {
                lemonToast.error('Failed to add insight to dashboard')
                throw e
            } finally {
                actions.setDashboardWithActiveAPICall(null)
            }
        },
        removeFromDashboard: async ({ dashboardId }): Promise<void> => {
            actions.updateInsight(
                {
                    dashboards: (values.insight.dashboards || []).filter((d) => d !== dashboardId),
                    dashboard_tiles: (values.insight.dashboard_tiles || []).filter(
                        (dt) => dt.dashboard_id !== dashboardId
                    ),
                },
                () => {
                    actions.reportRemovedInsightFromDashboard(values.insight, dashboardId)
                    lemonToast.success('Insight removed from dashboard')
                }
            )
        },
    })),
])
