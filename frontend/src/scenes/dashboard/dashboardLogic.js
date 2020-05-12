import { kea } from 'kea'
import api from 'lib/api'
import { dashboardsModel } from '~/models/dashboardsModel'
import { prompt } from 'lib/logic/prompt'
import { router } from 'kea-router'
import React from 'react'

export const dashboardLogic = kea({
    key: props => props.id,

    actions: () => ({
        addNewDashboard: true,
        renameDashboard: true,
        renameDashboardItem: id => ({ id }),
        renameDashboardItemSuccess: item => ({ item }),
        updateLayouts: layouts => ({ layouts }),
        saveLayouts: true,
        updateItemColor: (id, color) => ({ id, color }),
    }),

    loaders: ({ props }) => ({
        items: [
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

    reducers: () => ({
        items: {
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
            updateItemColor: (state, { id, color }) => state.map(i => (i.id === id ? { ...i, color } : i)),
        },
    }),

    selectors: ({ props, selectors }) => ({
        dashboard: [
            () => [dashboardsModel.selectors.dashboards],
            dashboards => dashboards.find(d => d.id === props.id) || null,
        ],
        breakpoints: [() => [], () => ({ lg: 1800, sm: 940, xs: 480, xxs: 0 })],
        cols: [() => [], () => ({ lg: 24, sm: 12, xs: 6, xxs: 2 })],
        layouts: [
            () => [selectors.items, selectors.cols],
            (items, cols) => {
                const layouts = {}
                Object.keys(cols).forEach(col => {
                    layouts[col] = items.map((item, index) => {
                        if (item.layouts && item.layouts[col]) {
                            return item.layouts[col]
                        } else {
                            return {
                                i: `${item.id}`,
                                x: index % 2 === 0 ? 0 : 6,
                                y: Math.floor(index / 2),
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
                items: values.items.map(item => ({ id: item.id, layouts: item.layouts })),
            })
        },

        updateItemColor: ({ id, color }) => {
            api.update(`api/dashboard_item/${id}`, { color })
        },
    }),
})
