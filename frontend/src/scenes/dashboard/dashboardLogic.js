import { kea } from 'kea'
import api from 'lib/api'
import { dashboardsModel } from '~/models/dashboardsModel'
import { prompt } from 'lib/logic/prompt'
import { router } from 'kea-router'
import { toast } from 'react-toastify'
import { Link } from 'lib/components/Link'
import React from 'react'
import { isAndroidOrIOS, clearDOMTextSelection } from 'lib/utils'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { PATHS_VIZ, ACTIONS_LINE_GRAPH_LINEAR } from 'lib/constants'
import { ViewType } from 'scenes/insights/insightLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export const dashboardLogic = kea({
    connect: [dashboardsModel, dashboardItemsModel, eventUsageLogic],

    key: (props) => props.id,

    actions: () => ({
        addNewDashboard: true,
        renameDashboard: true,
        setIsSharedDashboard: (id, isShared) => ({ id, isShared }),
        updateLayouts: (layouts) => ({ layouts }),
        updateContainerWidth: (containerWidth, columns) => ({ containerWidth, columns }),
        saveLayouts: true,
        updateItemColor: (id, color) => ({ id, color }),
        enableDragging: true,
        enableWobblyDragging: true,
        disableDragging: true,
        refreshDashboardItem: (id) => ({ id }),
    }),

    loaders: ({ props }) => ({
        allItems: [
            [],
            {
                loadDashboardItems: async () => {
                    try {
                        const dashboard = await api.get(
                            `api/dashboard/${props.id}${props.shareToken ? '/?share_token=' + props.shareToken : ''}`
                        )
                        eventUsageLogic.actions.reportDashboardViewed(dashboard, !!props.shareToken)
                        return dashboard
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
            [dashboardItemsModel.actions.renameDashboardItemSuccess]: (state, { item }) => {
                return { ...state, items: state.items.map((i) => (i.id === item.id ? item : i)) }
            },
            updateLayouts: (state, { layouts }) => {
                let itemLayouts = {}
                state.items.forEach((item) => {
                    itemLayouts[item.id] = {}
                })

                Object.entries(layouts).forEach(([col, layout]) => {
                    layout.forEach((layoutItem) => {
                        if (!itemLayouts[layoutItem.i]) {
                            itemLayouts[layoutItem.i] = {}
                        }
                        itemLayouts[layoutItem.i][col] = layoutItem
                    })
                })

                return { ...state, items: state.items.map((item) => ({ ...item, layouts: itemLayouts[item.id] })) }
            },
            [dashboardsModel.actions.updateDashboardItem]: (state, { item }) => {
                return { ...state, items: state.items.map((i) => (i.id === item.id ? item : i)) }
            },
            updateItemColor: (state, { id, color }) => {
                return { ...state, items: state.items.map((i) => (i.id === id ? { ...i, color } : i)) }
            },
            [dashboardItemsModel.actions.duplicateDashboardItemSuccess]: (state, { item }) => {
                return { ...state, items: item.dashboard === parseInt(props.id) ? [...state.items, item] : state.items }
            },
        },
        draggingEnabled: [
            () => (isAndroidOrIOS() ? 'off' : 'on'),
            {
                enableDragging: () => 'on',
                enableWobblyDragging: () => 'wobbly',
                disableDragging: () => 'off',
            },
        ],
        containerWidth: [
            null,
            {
                updateContainerWidth: (_, { containerWidth }) => containerWidth,
            },
        ],
        columns: [
            null,
            {
                updateContainerWidth: (_, { columns }) => columns,
            },
        ],
    }),
    selectors: ({ props, selectors }) => ({
        items: [() => [selectors.allItems], (allItems) => allItems?.items?.filter((i) => !i.deleted)],
        itemsLoading: [() => [selectors.allItemsLoading], (allItemsLoading) => allItemsLoading],
        dashboard: [
            () => [selectors.allItems, dashboardsModel.selectors.dashboards],
            (allItems, dashboards) => {
                let dashboard = dashboards.find((d) => d.id === props.id) || false
                return dashboard ? dashboard : allItems
            },
        ],
        breakpoints: [() => [], () => ({ lg: 1600, sm: 940, xs: 480, xxs: 0 })],
        cols: [() => [], () => ({ lg: 24, sm: 12, xs: 6, xxs: 2 })],
        sizeKey: [
            (s) => [s.columns, s.cols],
            (columns, cols) => {
                const [size] = Object.entries(cols).find(([, value]) => value === columns) || []
                return size
            },
        ],
        layouts: [
            () => [selectors.items, selectors.cols],
            (items, cols) => {
                const allLayouts = {}
                Object.keys(cols).forEach((col) => {
                    const layouts = items
                        .filter((i) => !i.deleted)
                        .map((item) => {
                            const isRetention =
                                item.filters.insight === ViewType.RETENTION &&
                                item.filters.display === ACTIONS_LINE_GRAPH_LINEAR
                            const defaultWidth = isRetention || item.filters.display === PATHS_VIZ ? 8 : 6
                            const defaultHeight = isRetention ? 8 : item.filters.display === PATHS_VIZ ? 12.5 : 5
                            const layout = item.layouts && item.layouts[col]
                            const { x, y, w, h } = layout || {}
                            const width = Math.min(w || defaultWidth, cols[col])
                            return {
                                i: `${item.id}`,
                                x: Number.isInteger(x) && x + width - 1 < cols[col] ? x : 0,
                                y: Number.isInteger(y) ? y : Infinity,
                                w: width,
                                h: h || defaultHeight,
                            }
                        })

                    const cleanLayouts = layouts.filter(({ y }) => y !== Infinity)

                    // array of -1 for each column
                    const lowestPoints = Array.from(Array(cols[col])).map(() => -1)

                    // set the lowest point for each column
                    cleanLayouts.forEach(({ x, y, w, h }) => {
                        for (let i = x; i <= x + w - 1; i++) {
                            lowestPoints[i] = Math.max(lowestPoints[i], y + h - 1)
                        }
                    })

                    layouts
                        .filter(({ y }) => y === Infinity)
                        .forEach(({ i, w, h }) => {
                            // how low are things in "w" consecutive of columns
                            const segmentCount = cols[col] - w + 1
                            const lowestSegments = Array.from(Array(segmentCount)).map(() => -1)
                            for (let i = 0; i < segmentCount; i++) {
                                for (let j = i; j <= i + w - 1; j++) {
                                    lowestSegments[i] = Math.max(lowestSegments[i], lowestPoints[j])
                                }
                            }

                            let lowestIndex = 0
                            let lowestDepth = lowestSegments[0]

                            lowestSegments.forEach((depth, index) => {
                                if (depth < lowestDepth) {
                                    lowestIndex = index
                                    lowestDepth = depth
                                }
                            })

                            cleanLayouts.push({
                                i,
                                x: lowestIndex,
                                y: lowestDepth + 1,
                                w,
                                h,
                            })

                            for (let i = lowestIndex; i <= lowestIndex + w - 1; i++) {
                                lowestPoints[i] = Math.max(lowestPoints[i], lowestDepth + h)
                            }
                        })

                    allLayouts[col] = cleanLayouts
                })
                return allLayouts
            },
        ],
        layout: [(s) => [s.layouts, s.sizeKey], (layouts, sizeKey) => layouts[sizeKey]],
        layoutForItem: [
            (s) => [s.layout],
            (layout) => {
                const layoutForItem = {}
                if (layout) {
                    for (const obj of layout) {
                        layoutForItem[obj.i] = obj
                    }
                }
                return layoutForItem
            },
        ],
    }),
    events: ({ actions, cache }) => ({
        afterMount: [actions.loadDashboardItems],
        beforeUnmount: () => {
            if (cache.draggingToastId) {
                toast.dismiss(cache.draggingToastId)
                cache.draggingToastId = null
            }
        },
    }),

    listeners: ({ actions, values, key, cache }) => ({
        addNewDashboard: async () => {
            prompt({ key: `new-dashboard-${key}` }).actions.prompt({
                title: 'New dashboard',
                placeholder: 'Please enter a name',
                value: '',
                error: 'You must enter name',
                success: (name) => dashboardsModel.actions.addDashboard({ name }),
            })
        },

        [dashboardsModel.actions.addDashboardSuccess]: ({ dashboard }) => {
            router.actions.push(`/dashboard/${dashboard.id}`)
        },

        setIsSharedDashboard: ({ id, isShared }) => {
            dashboardsModel.actions.setIsSharedDashboard({ id, isShared })
        },

        renameDashboard: async () => {
            prompt({ key: `rename-dashboard-${key}` }).actions.prompt({
                title: 'Rename dashboard',
                placeholder: 'Please enter the new name',
                value: values.dashboard.name,
                error: 'You must enter name',
                success: (name) => dashboardsModel.actions.renameDashboard({ id: values.dashboard.id, name }),
            })
        },

        updateLayouts: () => {
            actions.saveLayouts()
        },

        saveLayouts: async (_, breakpoint) => {
            await breakpoint(300)
            await api.update(`api/dashboard_item/layouts`, {
                items: values.items.map((item) => {
                    const layouts = {}
                    Object.entries(item.layouts).forEach(([key, layout]) => {
                        const { i, ...rest } = layout // eslint-disable-line
                        layouts[key] = rest
                    })
                    return { id: item.id, layouts }
                }),
            })
        },

        updateItemColor: ({ id, color }) => {
            api.update(`api/insight/${id}`, { color })
        },

        enableWobblyDragging: () => {
            clearDOMTextSelection()
            window.setTimeout(clearDOMTextSelection, 200)
            window.setTimeout(clearDOMTextSelection, 1000)

            if (!cache.draggingToastId) {
                cache.draggingToastId = toast(
                    <>
                        <p className="headline">Rearranging panels!</p>
                        <p>
                            <Link onClick={() => actions.disableDragging()}>Click here</Link> to stop.
                        </p>
                    </>,
                    {
                        autoClose: false,
                        onClick: () => actions.disableDragging(),
                        closeButton: false,
                        className: 'drag-items-toast',
                    }
                )
            }
        },
        enableDragging: () => {
            if (cache.draggingToastId) {
                toast.dismiss(cache.draggingToastId)
                cache.draggingToastId = null
            }
        },
        disableDragging: () => {
            if (cache.draggingToastId) {
                toast.dismiss(cache.draggingToastId)
                cache.draggingToastId = null
            }
        },
        refreshDashboardItem: async ({ id }) => {
            const dashboardItem = await api.get(`api/insight/${id}`)
            dashboardsModel.actions.updateDashboardItem(dashboardItem)
            if (dashboardItem.refreshing) {
                setTimeout(() => actions.refreshDashboardItem(id), 1000)
            }
        },
    }),
})
