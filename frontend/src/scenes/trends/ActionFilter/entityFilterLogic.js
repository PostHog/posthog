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
        order: index,
    }))

    return {
        [EntityTypes.ACTIONS]: filters.filter(filter => filter.type === EntityTypes.ACTIONS),
        [EntityTypes.EVENTS]: filters.filter(filter => filter.type === EntityTypes.EVENTS),
        [EntityTypes.NEW_ENTITY]: filters.filter(filter => filter.type === EntityTypes.NEW_ENTITY),
    }
}

// required props:
// - filters
// - setFilters
// - typeKey
export const entityFilterLogic = kea({
    key: props => props.typeKey,
    connect: {
        values: [userLogic, ['eventNames'], actionsModel, ['actions']],
    },
    actions: () => ({
        selectFilter: filter => ({ filter }),
        updateFilterMath: filter => ({
            type: filter.type,
            value: filter.value,
            math: filter.math,
            index: filter.index,
        }),
        updateFilter: filter => ({ type: filter.type, index: filter.index, value: filter.value, name: filter.name }),
        removeLocalFilter: filter => ({ value: filter.value, type: filter.type, index: filter.index }),
        addFilter: true,
        updateFilterProperty: filter => ({ properties: filter.properties, index: filter.index }),
        setFilters: filters => ({ filters }),
        setLocalFilters: filters => ({ filters }),
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
    }),

    selectors: ({ selectors }) => ({
        entities: [
            () => [selectors.eventNames, selectors.actions],
            (events, actions) => {
                return {
                    [EntityTypes.ACTIONS]: actions,
                    [EntityTypes.EVENTS]: events.map(event => ({ id: event, name: event })),
                }
            },
        ],
        filters: [() => [selectors.localFilters], localFilters => toFilters(localFilters)],
    }),

    listeners: ({ actions, values, props }) => ({
        updateFilter: ({ type, index, name, value }) => {
            actions.setFilters(
                values.localFilters.map((filter, i) => (i === index ? { ...filter, id: value, name, type } : filter))
            )
            actions.selectFilter(null)
        },
        updateFilterProperty: ({ properties, index }) => {
            actions.setFilters(
                values.localFilters.map((filter, i) => (i === index ? { ...filter, properties } : filter))
            )
        },
        updateFilterMath: ({ math, index }) => {
            actions.setFilters(values.localFilters.map((filter, i) => (i === index ? { ...filter, math } : filter)))
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
        setFilters: ({ filters }) => {
            props.setFilters(toFilters(filters))
        },
    }),
})
