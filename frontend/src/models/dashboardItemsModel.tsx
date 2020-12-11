import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { prompt } from 'lib/logic/prompt'
import { toast } from 'react-toastify'
import { DashboardItemType } from '~/types'
import { dashboardsModel } from './dashboardsModel'
import { Link } from 'lib/components/Link'

export const dashboardItemsModel = kea({
    actions: () => ({
        renameDashboardItem: (item) => ({ item }),
        renameDashboardItemSuccess: (item) => ({ item }),
        duplicateDashboardItem: (item, dashboardId, move = false) => ({ item, dashboardId, move }),
        duplicateDashboardItemSuccess: (item) => ({ item }),
    }),
    listeners: ({ actions }) => ({
        renameDashboardItem: async ({ item }) => {
            prompt({ key: `rename-dashboard-item-${item.id}` }).actions.prompt({
                title: 'Rename panel',
                placeholder: 'Please enter the new name',
                value: item.name,
                error: 'You must enter name',
                success: async (name: string) => {
                    item = await api.update(`api/dashboard_item/${item.id}`, { name })
                    toast('Succesfully renamed item')
                    actions.renameDashboardItemSuccess(item)
                },
            })
        },
        duplicateDashboardItem: async ({
            item,
            dashboardId,
            move,
        }: {
            item: DashboardItemType
            dashboardId: number
            move: boolean
        }) => {
            if (!item) {
                return
            }

            const layouts = {}
            Object.entries(item.layouts || {}).forEach(([size, { w, h }]) => {
                layouts[size] = { w, h }
            })

            const { id: _discard, ...rest } = item // eslint-disable-line
            const newItem = dashboardId ? { ...rest, dashboard: dashboardId, layouts } : { ...rest, layouts }
            const addedItem = await api.create('api/dashboard_item', newItem)

            const dashboard = dashboardId ? dashboardsModel.values.rawDashboards[dashboardId] : null

            if (move) {
                const deletedItem = await api.update(`api/dashboard_item/${item.id}`, {
                    deleted: true,
                })
                dashboardsModel.actions.updateDashboardItem(deletedItem)

                const toastId = toast(
                    <div data-attr="success-toast">
                        Panel moved to{' '}
                        <Link to={`/dashboard/${dashboard.id}`} onClick={() => toast.dismiss(toastId)}>
                            {dashboard.name || 'Untitled'}
                        </Link>
                        .&nbsp;
                        <Link
                            onClick={async () => {
                                toast.dismiss(toastId)
                                const [restoredItem, deletedItem] = await Promise.all([
                                    api.update(`api/dashboard_item/${item.id}`, { deleted: false }),
                                    api.update(`api/dashboard_item/${addedItem.id}`, {
                                        deleted: true,
                                    }),
                                ])
                                toast(<div>Panel move reverted!</div>)
                                dashboardsModel.actions.updateDashboardItem(restoredItem)
                                dashboardsModel.actions.updateDashboardItem(deletedItem)
                            }}
                        >
                            Undo
                        </Link>
                    </div>
                )
            } else if (!move && dashboardId) {
                // copy
                const toastId = toast(
                    <div data-attr="success-toast">
                        Panel copied to{' '}
                        <Link to={`/dashboard/${dashboard.id}`} onClick={() => toast.dismiss(toastId)}>
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
