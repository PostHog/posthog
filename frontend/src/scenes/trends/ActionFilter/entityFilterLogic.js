import { kea } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { EntityTypes } from '../trendsLogic'
import { userLogic } from 'scenes/userLogic'

function toLocalFilters(filters) {
    return [
        ...(filters[EntityTypes.ACTIONS] || []),
        ...(filters[EntityTypes.EVENTS] || []),
        ...(filters[EntityTypes.NEW_ENTITY] || []),
    ]
        .sort((a, b) => a.order - b.order)
        .map((filter, order) => ({ ...filter, order }))
}

function toFilters(localFilters) {
    const filters = localFilters.map((filter, index) => ({
        ...filter,
        order: 'order' in filter ? filter.order : index,
    }))

    return {
        [EntityTypes.ACTIONS]: filters.filter((filter) => filter.type === EntityTypes.ACTIONS),
        [EntityTypes.EVENTS]: filters.filter((filter) => filter.type === EntityTypes.EVENTS),
        [EntityTypes.NEW_ENTITY]: filters.filter((filter) => filter.type === EntityTypes.NEW_ENTITY),
    }
}

function getHeight(id, heights) {
    const LAYOUT_HEIGHT_CLOSED = 1
    if (heights && heights[id]) {
        return heights[id]
    }
    return LAYOUT_HEIGHT_CLOSED
}

function toLayouts(localFilters, heights) {
    return localFilters.map((filter) => ({
        i: filter.id ? filter.id.toString() : filter.id,
        x: 1,
        y: filter.order,
        w: 1,
        h: getHeight(filter.id, heights),
        isDraggable: true,
    }))
}

function toHeights(layouts) {
    return layouts.reduce(
        (heights, layout) => ({
            ...heights,
            [layout.id]: layout.h,
        }),
        {}
    )
}

function orderFilters(filters, filterPositions) {
    return filters
        .map((filter) => ({ ...filter, order: filterPositions[filter.id] }))
        .sort((a, b) => a.order - b.order)
        .map((filter, order) => ({ ...filter, order }))
}

// required props:
// - filters
// - setFilters
// - typeKey
export const entityFilterLogic = kea({
    key: (props) => props.typeKey,
    connect: {
        values: [userLogic, ['eventNames'], actionsModel, ['actions']],
    },
    actions: () => ({
        selectFilter: (filter) => ({ filter }),
        updateFilterMath: (filter) => ({
            type: filter.type,
            value: filter.value,
            math: filter.math,
            math_property: filter.math_property,
            index: filter.index,
        }),
        updateFilter: (filter) => ({ type: filter.type, index: filter.index, value: filter.value, name: filter.name }),
        removeLocalFilter: (filter) => ({ value: filter.value, type: filter.type, index: filter.index }),
        addFilter: true,
        updateFilterProperty: (filter) => ({ properties: filter.properties, index: filter.index }),
        setFilters: (filters) => ({ filters }),
        setLayoutHeight: (id, isOpen, properties) => ({ id, isOpen, properties }),
        setLayouts: (filters, heights) => ({ filters, heights }),
        setLocalFilters: (filters) => ({ filters }),
        orderFilters: (filterPositions) => ({ filterPositions }),
    }),

    reducers: ({ props }) => ({
        selectedFilter: [
            null,
            {
                selectFilter: (state, { filter }) => filter,
            },
        ],
        localFilters: [
            toLocalFilters(props.filters),
            {
                setLocalFilters: (_, { filters }) => toLocalFilters(filters),
            },
        ],
        layouts: [
            toLayouts(toLocalFilters(props.filters)),
            {
                setLayouts: (_, { filters, heights }) => toLayouts(filters, heights),
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        entities: [
            () => [selectors.eventNames, selectors.actions],
            (events, actions) => {
                return {
                    [EntityTypes.ACTIONS]: actions,
                    [EntityTypes.EVENTS]: events.map((event) => ({ id: event, name: event })),
                }
            },
        ],
        filters: [() => [selectors.localFilters], (localFilters) => toFilters(localFilters)],
    }),

    listeners: ({ actions, values, props }) => ({
        updateFilter: ({ type, index, name, value }) => {
            actions.setFilters(
                values.localFilters.map((filter, i) => (i === index ? { ...filter, id: value, name, type } : filter))
            )
            !props.singleMode && actions.selectFilter(null)
        },
        updateFilterProperty: ({ properties, index }) => {
            actions.setFilters(
                values.localFilters.map((filter, i) => (i === index ? { ...filter, properties } : filter))
            )
        },
        updateFilterMath: ({ math, math_property, index }) => {
            actions.setFilters(
                values.localFilters.map((filter, i) => (i === index ? { ...filter, math, math_property } : filter))
            )
        },
        removeLocalFilter: ({ index }) => {
            actions.setFilters(values.localFilters.filter((_, i) => i !== index))
        },
        addFilter: () => {
            actions.setFilters([
                ...values.localFilters,
                { id: null, type: EntityTypes.NEW_ENTITY, order: values.localFilters.length },
            ])
        },
        orderFilters: ({ filterPositions }) => {
            actions.setFilters(orderFilters(values.localFilters, filterPositions))
        },
        setFilters: ({ filters }) => {
            props.setFilters(toFilters(filters))
            actions.setLayouts(filters, toHeights(values.layouts))
        },
        setLayoutHeight: ({ id, isOpen, properties }) => {
            const LAYOUT_HEIGHT_CLOSED = 1
            const LAYOUT_HEIGHT_OPEN = 2
            const heights = {
                [id]: isOpen ? LAYOUT_HEIGHT_OPEN + properties : LAYOUT_HEIGHT_CLOSED,
            }
            actions.setLayouts(values.localFilters, heights)
        },
    }),
    events: ({ actions, props, values }) => ({
        afterMount: () => {
            if (props.singleMode) {
                const filter = { id: null, type: EntityTypes.NEW_ENTITY, order: values.localFilters.length }
                actions.setLocalFilters({ [`${EntityTypes.NEW_ENTITY}`]: [filter] })
                actions.selectFilter({ filter, type: EntityTypes.NEW_ENTITY, index: 0 })
            }
        },
    }),
})
