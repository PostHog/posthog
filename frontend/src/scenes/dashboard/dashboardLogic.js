import { kea } from 'kea'
import api from 'lib/api'
import { dashboardsModel } from '~/models/dashboardsModel'
import { prompt } from 'lib/logic/prompt'
import { router } from 'kea-router'
import { toast } from 'react-toastify'
import { Link } from 'lib/components/Link'
import React from 'react'

export const dashboardLogic = kea({
    key: props => props.id,

    actions: () => ({
        addNewDashboard: true,
        renameDashboard: true,
        renameDashboardItem: id => ({ id }),
        renameDashboardItemSuccess: item => ({ item }),
        duplicateDashboardItem: (id, dashboardId, move = false) => ({ id, dashboardId, move }),
        duplicateDashboardItemSuccess: item => ({ item }),
        updateLayouts: layouts => ({ layouts }),
        saveLayouts: true,
        updateItemColor: (id, color) => ({ id, color }),
    }),

    loaders: ({ props }) => ({
        allItems: [
            [],
            {
                loadDashboardItems: async () => {
                    try {
                        const { items } = await api.get(`api/dashboard/${props.id}`)
                        return items
                    } catch (error) {
                        if (error.status === 404) {
                            // silently escape
                            return []
                        }
                        throw error
                    }
                },
            },
        ],
    }),

    reducers: ({ props }) => ({
        allItems: {
            renameDashboardItemSuccess: (state, { item }) => state.map(i => (i.id === item.id ? item : i)),
            updateLayouts: (state, { layouts }) => {
                let itemLayouts = {}
                state.forEach(item => {
                    itemLayouts[item.id] = {}
                })

                Object.entries(layouts).forEach(([col, layout]) => {
                    layout.forEach(layoutItem => {
                        itemLayouts[layoutItem.i][col] = layoutItem
                    })
                })

                return state.map(item => ({ ...item, layouts: itemLayouts[item.id] }))
            },
            [dashboardsModel.actions.updateDashboardItem]: (state, { item }) => {
                return state.map(i => (i.id === item.id ? item : i))
            },
            updateItemColor: (state, { id, color }) => state.map(i => (i.id === id ? { ...i, color } : i)),
            duplicateDashboardItemSuccess: (state, { item }) =>
                item.dashboard === parseInt(props.id) ? [...state, item] : state,
        },
    }),

    selectors: ({ props, selectors }) => ({
        items: [() => [selectors.allItems], allItems => allItems.filter(i => !i.deleted)],
        itemsLoading: [() => [selectors.allItemsLoading], allItemsLoading => allItemsLoading],
        dashboard: [
            () => [dashboardsModel.selectors.dashboards],
            dashboards => dashboards.find(d => d.id === props.id) || null,
        ],
        breakpoints: [() => [], () => ({ lg: 1600, sm: 940, xs: 480, xxs: 0 })],
        cols: [() => [], () => ({ lg: 24, sm: 12, xs: 6, xxs: 2 })],
        layouts: [
            () => [selectors.items, selectors.cols],
            (items, cols) => {
                const layouts = {}
                Object.keys(cols).forEach(col => {
                    layouts[col] = items.map(item => {
                        if (item.layouts && item.layouts[col]) {
                            return { ...item.layouts[col], i: `${item.id}` }
                        } else {
                            return {
                                i: `${item.id}`,
                                x: 0,
                                y: Infinity,
                                w: 6,
                                h: 5,
                            }
                        }
                    })
                })
                return layouts
            },
        ],
    }),

    events: ({ actions }) => ({
        afterMount: [actions.loadDashboardItems],
    }),

    listeners: ({ actions, values, key }) => ({
        addNewDashboard: async () => {
            prompt({ key: `new-dashboard-${key}` }).actions.prompt({
                title: 'New dashboard',
                placeholder: 'Please enter a name',
                value: '',
                error: 'You must enter name',
                success: name => dashboardsModel.actions.addDashboard({ name }),
            })
        },

        [dashboardsModel.actions.addDashboardSuccess]: ({ dashboard }) => {
            router.actions.push(`/dashboard/${dashboard.id}`)
        },

        renameDashboard: async () => {
            prompt({ key: `rename-dashboard-${key}` }).actions.prompt({
                title: 'Rename dashboard',
                placeholder: 'Please enter the new name',
                value: values.dashboard.name,
                error: 'You must enter name',
                success: name => dashboardsModel.actions.renameDashboard({ id: values.dashboard.id, name }),
            })
        },

        renameDashboardItem: async ({ id }) => {
            prompt({ key: `rename-dashboard-item-${id}` }).actions.prompt({
                title: 'Rename panel',
                placeholder: 'Please enter the new name',
                value: values.items.find(item => item.id === id)?.name,
                error: 'You must enter name',
                success: async name => {
                    const item = await api.update(`api/dashboard_item/${id}`, { name })
                    actions.renameDashboardItemSuccess(item)
                },
            })
        },

        updateLayouts: () => {
            actions.saveLayouts()
        },

        saveLayouts: async (_, breakpoint) => {
            await breakpoint(300)
            await api.update(`api/dashboard_item/layouts`, {
                items: values.items.map(item => {
                    const layouts = {}
                    Object.entries(item.layouts).forEach(([key, layout]) => {
                        const { i, ...rest } = layout
                        layouts[key] = rest
                    })
                    return { id: item.id, layouts }
                }),
            })
        },

        updateItemColor: ({ id, color }) => {
            api.update(`api/dashboard_item/${id}`, { color })
        },

        duplicateDashboardItem: async ({ id, dashboardId, move }) => {
            const item = values.items.find(item => item.id === id)
            if (item) {
                const { id: _discard, ...rest } = item
                const newItem = dashboardId ? { ...rest, dashboard: dashboardId } : { ...rest }
                const addedItem = await api.create('api/dashboard_item', newItem)

                if (move) {
                    const deletedItem = await api.update(`api/dashboard_item/${item.id}`, { deleted: true })
                    dashboardsModel.actions.updateDashboardItem(deletedItem)

                    const toastId = toast(
                        <div>
                            Panel moved to dashboard.&nbsp;
                            <Link
                                onClick={async () => {
                                    toast.dismiss(toastId)
                                    const [restoredItem, deletedItem] = await Promise.all([
                                        api.update(`api/dashboard_item/${item.id}`, { deleted: false }),
                                        api.update(`api/dashboard_item/${addedItem.id}`, { deleted: true }),
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
                } else {
                    actions.duplicateDashboardItemSuccess(addedItem)

                    if (dashboardId) {
                        const toastId = toast(
                            <div>
                                Panel added to dashboard.&nbsp;
                                <Link to={`/dashboard/${dashboardId}`} onClick={() => toast.dismiss(toastId)}>
                                    Click here to see it.
                                </Link>
                            </div>
                        )
                    } else {
                        toast(<div>Panel duplicated!</div>)
                    }
                }
            }
        },
    }),
})
