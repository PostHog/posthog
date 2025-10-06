import FuseClass from 'fuse.js'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
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
    }),
    reducers({
        searchQuery: ['', { setSearchQuery: (_, { query }) => query }],
        scrollIndex: [-1 as number, { setScrollIndex: (_, { index }) => index }],
        dashboardWithActiveAPICall: [
            null as number | null,
            {
                addToDashboard: (_, { dashboardId }) => dashboardId,
                removeFromDashboard: (_, { dashboardId }) => dashboardId,
                updateInsightSuccess: () => null,
                updateInsightFailure: () => null,
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
        },

        [dashboardsModel.actionTypes.addDashboardSuccess]: async ({ dashboard }) => {
            actions.reportCreatedDashboardFromModal()
            actions.addToDashboard(dashboard.id)
            actions.setScrollIndex(values.orderedDashboards.findIndex((d) => d.id === dashboard.id))
        },

        addToDashboard: async ({ dashboardId }) => {
            // TODO be able to update not by patching `dashboards` against insight
            // either patch dashboard_tiles on the insight or add a dashboard_tiles API
            actions.updateInsight(
                {
                    dashboards: [...(values.insight.dashboards || []), dashboardId],
                },
                () => {
                    actions.reportSavedInsightToDashboard(values.insight, dashboardId)
                    dashboardsModel.actions.tileAddedToDashboard(dashboardId)
                    lemonToast.success('Insight added to dashboard', {
                        button: {
                            label: 'View dashboard',
                            action: () => router.actions.push(urls.dashboard(dashboardId)),
                        },
                    })
                }
            )
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
