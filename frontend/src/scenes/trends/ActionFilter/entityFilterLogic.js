import { kea } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { EntityTypes } from '../trendsLogic'
import { userLogic } from 'scenes/userLogic'

function toLocalFilters(filters) {
    return [...(filters.actions || []), ...(filters.events || [])]
        .sort((a, b) => a.order - b.order)
        .map((filter, order) => ({ ...filter, order }))
}

function toFilters(localFilters) {
    return {
        [EntityTypes.ACTIONS]: localFilters.filter(filter => filter.type === EntityTypes.ACTIONS),
        [EntityTypes.EVENTS]: localFilters.filter(filter => filter.type === EntityTypes.EVENTS),
        [EntityTypes.NEW]: localFilters.filter(filter => filter.type === EntityTypes.NEW),
    }
}

// required props:
// - filters
// - setFilters
// - typeKey
//
// optional props:
// - setDefaultIfEmpty
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
        updateFilter: filter => ({ type: filter.type, index: filter.index, value: filter.value }),
        removeLocalFilter: filter => ({ value: filter.value, type: filter.type, index: filter.index }),
        addFilter: true,
        updateFilterProperty: filter => ({ properties: filter.properties, index: filter.index }),
        setFilters: filters => ({ filters }),
    }),

    reducers: () => ({
        selectedFilter: [
            null,
            {
                selectFilter: (state, { filter }) => filter,
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        allFilters: [
            () => [(_, props) => props.filters],
            propsFilters => {
                return toLocalFilters(propsFilters)
            },
        ],
        entities: [
            () => [selectors.eventNames, selectors.actions],
            (events, actions) => {
                return {
                    [EntityTypes.ACTIONS]: actions,
                    [EntityTypes.EVENTS]: events.map(event => ({ id: event, name: event })),
                }
            },
        ],
        filters: [() => [selectors.allFilters], allFilters => toFilters(allFilters)],
    }),

    listeners: ({ actions, values, props }) => ({
        updateFilter: ({ type, index, value }) => {
            actions.setFilters(
                values.allFilters.map((filter, i) => (i === index ? { ...filter, id: value, type } : filter))
            )
            actions.selectFilter(null)
        },
        updateFilterProperty: ({ properties, index }) => {
            actions.setFilters(values.allFilters.map((filter, i) => (i === index ? { ...filter, properties } : filter)))
        },
        updateFilterMath: ({ math, index }) => {
            actions.setFilters(values.allFilters.map((filter, i) => (i === index ? { ...filter, math } : filter)))
        },
        removeLocalFilter: ({ index }) => {
            actions.setFilters(values.allFilters.filter((_, i) => i !== index))
        },
        addFilter: () => {
            actions.setFilters([
                ...values.allFilters,
                { id: null, type: EntityTypes.NEW, order: values.allFilters.length },
            ])
        },
        setFilters: ({ filters }) => {
            props.setFilters(
                toFilters(
                    filters.map((filter, index) => ({
                        ...filter,
                        order: index,
                    }))
                )
            )
        },
    }),

    events: ({ actions, props, values }) => ({
        afterMount: () => {
            if (props.setDefaultIfEmpty && values.allFilters.length === 0 && values.eventNames) {
                let event = values.eventNames.indexOf('$pageview') >= -1 ? '$pageview' : values.eventNames[0]
                actions.setFilters([
                    {
                        id: event,
                        name: event,
                        type: EntityTypes.EVENTS,
                    },
                ])
            }
        },
    }),
})
