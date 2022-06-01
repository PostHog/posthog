import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { prompt } from 'lib/logic/prompt'
import { InsightModel } from '~/types'
import { dashboardsModel } from './dashboardsModel'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { teamLogic } from 'scenes/teamLogic'
import type { insightsModelType } from './insightsModelType'
import { lemonToast } from 'lib/components/lemonToast'
import { router } from 'kea-router'

export const insightsModel = kea<insightsModelType>({
    path: ['models', 'insightsModel'],
    connect: [prompt({ key: 'rename-insight' })],
    actions: () => ({
        renameInsight: (item: InsightModel) => ({ item }),
        renameInsightSuccess: (item: InsightModel) => ({ item }),
        duplicateInsight: (item: InsightModel, dashboardId?: number, move: boolean = false) => ({
            item,
            dashboardId,
            move,
        }),
        moveToDashboard: (item: InsightModel, fromDashboard: number, toDashboard: number, toDashboardName: string) => ({
            item,
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
        moveToDashboard: async ({ item, fromDashboard, toDashboard, toDashboardName }) => {
            if (!item) {
                return
            }

            const originalDashboards = item.dashboards || []
            const dashboards = [...originalDashboards.filter((d: number) => d !== fromDashboard), toDashboard]

            const updatedItem = await api.update(`api/projects/${teamLogic.values.currentTeamId}/insights/${item.id}`, {
                dashboards,
            })
            dashboardsModel.actions.updateDashboardItem(updatedItem, [fromDashboard, toDashboard])

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
                                `api/projects/${teamLogic.values.currentTeamId}/insights/${item.id}`,
                                {
                                    dashboards: originalDashboards,
                                }
                            )
                            lemonToast.success('Panel move reverted')
                            dashboardsModel.actions.updateDashboardItem(restoredItem, [fromDashboard, toDashboard])
                        },
                    },
                }
            )
        },
        duplicateInsight: async ({ item, dashboardId, move }) => {
            if (!item) {
                return
            }

            const layouts: Record<string, any> = {}
            Object.entries(item.layouts || {}).forEach(([size, { w, h }]) => {
                layouts[size] = { w, h }
            })

            const { id: _discard, short_id: __discard, ...rest } = item
            const newItem = dashboardId ? { ...rest, dashboards: [dashboardId], layouts } : { ...rest, layouts }
            const addedItem = await api.create(`api/projects/${teamLogic.values.currentTeamId}/insights`, newItem)

            const dashboard = dashboardId ? dashboardsModel.values.rawDashboards[dashboardId] : null

            if (move && dashboard) {
                const deletedItem = await api.update(
                    `api/projects/${teamLogic.values.currentTeamId}/insights/${item.id}`,
                    {
                        deleted: true,
                    }
                )
                dashboardsModel.actions.updateDashboardItem(deletedItem)

                lemonToast.success(
                    <>
                        Insight moved to{' '}
                        <b>
                            <Link to={urls.dashboard(dashboard.id)}>{dashboard.name || 'Untitled'}</Link>
                        </b>
                    </>,
                    {
                        button: {
                            label: 'Undo',
                            action: async () => {
                                const [restoredItem, removedItem] = await Promise.all([
                                    api.update(`api/projects/${teamLogic.values.currentTeamId}/insights/${item.id}`, {
                                        deleted: false,
                                    }),
                                    api.update(
                                        `api/projects/${teamLogic.values.currentTeamId}/insights/${addedItem.id}`,
                                        {
                                            deleted: true,
                                        }
                                    ),
                                ])
                                lemonToast.success('Panel move reverted')
                                dashboardsModel.actions.updateDashboardItem(restoredItem)
                                dashboardsModel.actions.updateDashboardItem(removedItem)
                            },
                        },
                    }
                )
            } else if (!move && dashboardId && dashboard) {
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
        },
    }),
})
