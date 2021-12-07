import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { prompt } from 'lib/logic/prompt'
import { toast } from 'react-toastify'
import { InsightType } from '~/types'
import { dashboardsModel } from './dashboardsModel'
import { Link } from 'lib/components/Link'
import { dashboardItemsModelType } from './dashboardItemsModelType'
import { urls } from 'scenes/urls'
import { teamLogic } from 'scenes/teamLogic'

export const dashboardItemsModel = kea<dashboardItemsModelType>({
    path: ['models', 'dashboardItemsModel'],
    actions: () => ({
        renameDashboardItem: (item: InsightType) => ({ item }),
        renameDashboardItemSuccess: (item: InsightType) => ({ item }),
        duplicateDashboardItem: (item: InsightType, dashboardId?: number, move: boolean = false) => ({
            item,
            dashboardId,
            move,
        }),
        duplicateDashboardItemSuccess: (item: InsightType) => ({ item }),
    }),
    listeners: ({ actions }) => ({
        renameDashboardItem: async ({ item }) => {
            prompt({ key: `rename-dashboard-item-${item.short_id}` }).actions.prompt({
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
                    toast(`Successfully renamed insight from "${item.name}" to "${name}"`)
                    actions.renameDashboardItemSuccess(updatedItem)
                },
            })
        },
        duplicateDashboardItem: async ({ item, dashboardId, move }) => {
            if (!item) {
                return
            }

            const layouts: Record<string, any> = {}
            Object.entries(item.layouts || {}).forEach(([size, { w, h }]) => {
                layouts[size] = { w, h }
            })

            const { id: _discard, short_id: __discard, ...rest } = item // eslint-disable-line
            const newItem = dashboardId ? { ...rest, dashboard: dashboardId, layouts } : { ...rest, layouts }
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

                const toastId = toast(
                    <div data-attr="success-toast">
                        Panel moved to{' '}
                        <Link to={urls.dashboard(dashboard.id)} onClick={() => toast.dismiss(toastId)}>
                            {dashboard.name || 'Untitled'}
                        </Link>
                        .&nbsp;
                        <Link
                            to="#"
                            onClick={async () => {
                                toast.dismiss(toastId)
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
                                toast(<div>Panel move reverted!</div>)
                                dashboardsModel.actions.updateDashboardItem(restoredItem)
                                dashboardsModel.actions.updateDashboardItem(removedItem)
                            }}
                        >
                            Undo
                        </Link>
                    </div>
                )
            } else if (!move && dashboardId && dashboard) {
                // copy
                const toastId = toast(
                    <div data-attr="success-toast">
                        Panel copied to{' '}
                        <Link to={urls.dashboard(dashboard.id)} onClick={() => toast.dismiss(toastId)}>
                            {dashboard.name || 'Untitled'}
                        </Link>
                    </div>
                )
            } else {
                actions.duplicateDashboardItemSuccess(addedItem)
                toast(<div data-attr="success-toast">Panel duplicated!</div>)
            }
        },
    }),
})
