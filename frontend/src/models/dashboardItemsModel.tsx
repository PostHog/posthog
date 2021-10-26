import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { prompt } from 'lib/logic/prompt'
import { toast } from 'react-toastify'
import { DashboardItemType } from '~/types'
import { dashboardsModel } from './dashboardsModel'
import { Link } from 'lib/components/Link'
import { dashboardItemsModelType } from './dashboardItemsModelType'
import { urls } from 'scenes/urls'
import { teamLogic } from '../scenes/teamLogic'

export const dashboardItemsModel = kea<dashboardItemsModelType>({
    actions: () => ({
        renameDashboardItem: (item: DashboardItemType) => ({ item }),
        renameDashboardItemSuccess: (item: DashboardItemType) => ({ item }),
        duplicateDashboardItem: (item: DashboardItemType, dashboardId?: number, move: boolean = false) => ({
            item,
            dashboardId,
            move,
        }),
        duplicateDashboardItemSuccess: (item: DashboardItemType) => ({ item }),
    }),
    listeners: ({ actions }) => ({
        renameDashboardItem: async ({ item }) => {
            prompt({ key: `rename-dashboard-item-${item.id}` }).actions.prompt({
                title: 'Rename panel',
                placeholder: 'Please enter the new name',
                value: item.name,
                error: 'You must enter name',
                success: async (name: string) => {
                    item = await api.update(`api/projects/${teamLogic.values.currentTeamId}/insights/${item.id}`, {
                        name,
                    })
                    toast('Successfully renamed item')
                    actions.renameDashboardItemSuccess(item)
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

            const { id: _discard, ...rest } = item // eslint-disable-line
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
