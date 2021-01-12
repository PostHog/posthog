import { kea } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { EntityTypes } from '../trendsLogic'
import { userLogic } from 'scenes/userLogic'

export function toLocalFilters(filters) {
    return [
        ...(filters[EntityTypes.ACTIONS] || []),
        ...(filters[EntityTypes.EVENTS] || []),
        ...(filters[EntityTypes.NEW_ENTITY] || []),
    ]
        .sort((a, b) => a.order - b.order)
        .map((filter, order) => ({ ...filter, order }))
}

export function toFilters(localFilters) {
    const filters = localFilters.map((filter, index) => ({
        ...filter,
        order: index,
    }))

    return {
        [EntityTypes.ACTIONS]: filters.filter((filter) => filter.type === EntityTypes.ACTIONS),
        [EntityTypes.EVENTS]: filters.filter((filter) => filter.type === EntityTypes.EVENTS),
        [EntityTypes.NEW_ENTITY]: filters.filter((filter) => filter.type === EntityTypes.NEW_ENTITY),
    }
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
        updateFilter: (filter) => ({ type: filter.type, index: filter.index, id: filter.id, name: filter.name }),
        removeLocalFilter: (filter) => ({ value: filter.value, type: filter.type, index: filter.index }),
        addFilter: true,
        updateFilterProperty: (filter) => ({ properties: filter.properties, index: filter.index }),
        setFilters: (filters) => ({ filters }),
        setLocalFilters: (filters) => ({ filters }),
        setEntityFilterVisibility: (index, value) => ({ index, value }),
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
        entityFilterVisible: [
            {},
            {
                setEntityFilterVisibility: (state, { index, value }) => ({ ...state, [index]: value }),
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
        updateFilter: ({ type, index, name, id }) => {
            actions.setFilters(
                values.localFilters.map((filter, i) => (i === index ? { ...filter, id, name, type } : filter))
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
            if (values.localFilters.length > 0) {
                const lastFilter = values.localFilters[values.localFilters.length - 1]
                const order = lastFilter.order + 1
                actions.setFilters([...values.localFilters, { ...lastFilter, order }])
                actions.setEntityFilterVisibility(order, values.entityFilterVisible[lastFilter.order])
            } else {
                actions.setFilters([{ id: null, type: EntityTypes.NEW_ENTITY, order: 0 }])
            }
        },
        setFilters: ({ filters }) => {
            props.setFilters(toFilters(filters), filters)
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
