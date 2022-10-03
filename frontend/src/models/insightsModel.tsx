import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { prompt } from 'lib/logic/prompt'
import { DashboardTile, InsightModel } from '~/types'
import { dashboardsModel } from './dashboardsModel'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { teamLogic } from 'scenes/teamLogic'
import type { insightsModelType } from './insightsModelType'
import { lemonToast } from 'lib/components/lemonToast'
import { router } from 'kea-router'

export const insightsModel = kea<insightsModelType>({
    path: ['models', 'insightsModel'],
    connect: [prompt({ key: 'rename-insight' }), teamLogic],
    actions: () => ({
        renameInsight: (item: InsightModel) => ({ item }),
        renameInsightSuccess: (item: InsightModel) => ({ item }),
        /** duplicate an insight from the insight page */
        duplicateInsight: (item: InsightModel, dashboardId?: number) => ({
            item,
            dashboardId,
        }),
        moveToDashboard: (
            tile: DashboardTile,
            fromDashboard: number,
            toDashboard: number,
            toDashboardName: string
        ) => ({
            tile,
            fromDashboard,
            toDashboard,
            toDashboardName,
        }),
        duplicateInsightSuccess: (item: InsightModel) => ({ item }),
    }),
    listeners: ({ actions }) => ({
        renameInsight: async ({ item }) => {
            prompt({ key: 'rename-insight' }).actions.prompt({
                title: 'Rename insight',
                placeholder: 'Please enter the new name',
                value: item.name,
                error: 'You must enter name',
                success: async (name: string) => {
                    const updatedItem = await api.update(
                        `api/projects/${teamLogic.values.currentTeamId}/insights/${item.id}`,
                        {
                            name,
                        }
                    )
                    lemonToast.success(
                        <>
                            Renamed insight from <b>{item.name}</b> to <b>{name}</b>
                        </>
                    )
                    actions.renameInsightSuccess(updatedItem)
                },
            })
        },
        moveToDashboard: async ({ tile, fromDashboard, toDashboard, toDashboardName }) => {
            if (!tile || !tile.insight) {
                return
            }

            const originalDashboards = tile.insight.dashboards || []
            const dashboards = [...originalDashboards.filter((d: number) => d !== fromDashboard), toDashboard]

            const updatedInsight = await api.update(
                `api/projects/${teamLogic.values.currentTeamId}/insights/${tile.insight.id}`,
                {
                    dashboards,
                }
            )
            const updatedTile = {
                ...tile,
                insight: updatedInsight,
            }
            dashboardsModel.actions.updateDashboardTile(updatedTile, [fromDashboard])

            lemonToast.success(
                <>
                    Insight moved to{' '}
                    <b>
                        <Link to={urls.dashboard(toDashboard)}>{toDashboardName}</Link>
                    </b>
                </>,
                {
                    button: {
                        label: 'Undo',
                        action: async () => {
                            const restoredItem = await api.update(
                                `api/projects/${teamLogic.values.currentTeamId}/insights/${tile.insight.id}`,
                                {
                                    dashboards: originalDashboards,
                                }
                            )
                            const restoredTile = {
                                ...tile,
                                insight: restoredItem,
                            }
                            lemonToast.success('Panel move reverted')
                            dashboardsModel.actions.updateDashboardTile(restoredTile, [toDashboard])
                        },
                    },
                }
            )
        },
        duplicateInsight: async ({ item, dashboardId }) => {
            if (!item) {
                return
            }

            // TODO insight only has layouts in dashboard context -
            // const layouts: Record<string, any> = {}
            // Object.entries(item.layouts || {}).forEach(([size, { w, h }]) => {
            //     layouts[size] = { w, h }
            // })

            const { id: _discard, short_id: __discard, ...rest } = item
            const newItem = dashboardId ? { ...rest, dashboards: [dashboardId] } : { ...rest }
            const addedItem = await api.create(`api/projects/${teamLogic.values.currentTeamId}/insights`, newItem)

            const dashboard = dashboardId ? dashboardsModel.values.rawDashboards[dashboardId] : null

            if (dashboardId && dashboard) {
                lemonToast.success('Insight copied', {
                    button: {
                        label: `View ${dashboard.name}`,
                        action: () => router.actions.push(urls.dashboard(dashboard.id)),
                    },
                })
            } else {
                actions.duplicateInsightSuccess(addedItem)
                lemonToast.success('Insight duplicated')
            }
            lemonToast.error('Insight duplication not yet implemented ' + dashboardId)
        },
    }),
})
