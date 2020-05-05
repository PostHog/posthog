import { kea } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { EntityTypes } from '../trendsLogic'
import { userLogic } from 'scenes/userLogic'

function toLocalFilters(filters) {
    return [...(filters.actions || []), ...(filters.events || [])]
        .sort((a, b) => a.order - b.order)
        .map((filter, index) => ({ ...filter, order: index }))
}

function toFilters(localFilters) {
    return {
        [EntityTypes.ACTIONS]: localFilters.filter(filter => filter.type === EntityTypes.ACTIONS),
        [EntityTypes.EVENTS]: localFilters.filter(filter => filter.type === EntityTypes.EVENTS),
    }
}

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
        createNewFilter: true,
        setLocalFilters: filters => ({
            filters: filters.map((filter, index) => ({
                ...filter,
                order: typeof filter.order === undefined ? index : filter.order,
            })),
        }),
        updateFilterProperty: filter => ({ properties: filter.properties, index: filter.index }),
    }),

    reducers: ({ props }) => ({
        selectedFilter: [
            null,
            {
                selectFilter: (state, { filter }) => filter,
            },
        ],
        localFilters: [
            toLocalFilters(props.filters || props.defaultFilters || {}),
            {
                setLocalFilters: (state, { filters }) => filters,
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        allFilters: [
            () => [(_, props) => props.filters, selectors.localFilters],
            (propsFilters, localFilters) => {
                return typeof propsFilters === 'undefined' ? localFilters : toLocalFilters(propsFilters)
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
            let currentFilters = values.allFilters ? [...values.allFilters] : []
            currentFilters[index] = {
                id: value,
                type: type,
            }
            actions.setLocalFilters(currentFilters)
            actions.selectFilter(null)
        },
        updateFilterProperty: ({ properties, index }) => {
            let currentFilters = values.allFilters ? [...values.allFilters] : []
            currentFilters[index].properties = properties
            actions.setLocalFilters(currentFilters)
        },
        updateFilterMath: ({ math, index }) => {
            let currentFilters = values.allFilters ? [...values.allFilters] : []
            currentFilters[index].math = math
            actions.setLocalFilters(currentFilters)
        },
        removeLocalFilter: ({ index }) => {
            let currentFilters = values.allFilters ? [...values.allFilters] : []
            currentFilters.splice(index, 1)
            actions.setLocalFilters(currentFilters)
        },
        createNewFilter: state => {
            let currentFilters = values.allFilters ? [...values.allFilters] : []
            currentFilters.push({ id: null, type: EntityTypes.NEW, order: currentFilters.length })
            actions.setLocalFilters(currentFilters)
        },
        setLocalFilters: ({ filters }) => {
            props.setFilters(toFilters(filters))
        },
    }),

    events: ({ actions, props, values }) => ({
        afterMount: () => {
            if (props.setDefaultIfEmpty && values.allFilters.length === 0 && values.eventNames) {
                let event = values.eventNames.indexOf('$pageview') >= -1 ? '$pageview' : values.eventNames[0]
                actions.setLocalFilters([
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
