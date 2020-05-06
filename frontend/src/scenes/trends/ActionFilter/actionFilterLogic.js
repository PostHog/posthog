import { kea } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { EntityTypes } from '../trendsLogic'
import { userLogic } from 'scenes/userLogic'

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
        setLocalFilters: filters => ({ filters }),
        updateFilterProperty: filter => ({ properties: filter.properties, index: filter.index }),
    }),

    reducers: ({ actions, props }) => ({
        selectedFilter: [
            null,
            {
                [actions.selectFilter]: (state, { filter }) => filter,
            },
        ],
        allFilters: [
            [],
            {
                [actions.setLocalFilters]: (state, { filters }) =>
                    filters.map((filter, index) => ({ ...filter, order: index })),
                [actions.createNewFilter]: state => [
                    ...state,
                    { id: null, type: EntityTypes.NEW, order: state.length },
                ],
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
        filters: [
            () => [selectors.allFilters],
            allFilters => {
                return {
                    [EntityTypes.ACTIONS]: allFilters.filter(filter => filter.type === EntityTypes.ACTIONS),
                    [EntityTypes.EVENTS]: allFilters.filter(filter => filter.type === EntityTypes.EVENTS),
                }
            },
        ],
    }),

    listeners: ({ actions, values, props }) => ({
        [actions.updateFilter]: ({ type, index, value }) => {
            let currentFilters = values.allFilters ? [...values.allFilters] : []
            currentFilters[index] = {
                id: value,
                type: type,
            }
            actions.setLocalFilters(currentFilters)
            actions.selectFilter(null)
        },
        [actions.updateFilterProperty]: ({ properties, index }) => {
            let currentFilters = values.allFilters ? [...values.allFilters] : []
            currentFilters[index].properties = properties
            actions.setLocalFilters(currentFilters)
        },
        [actions.updateFilterMath]: ({ math, index }) => {
            let currentFilters = values.allFilters ? [...values.allFilters] : []
            currentFilters[index].math = math
            actions.setLocalFilters(currentFilters)
        },
        [actions.removeLocalFilter]: ({ index }) => {
            let currentFilters = values.allFilters ? [...values.allFilters] : []
            currentFilters.splice(index, 1)
            actions.setLocalFilters(currentFilters)
        },
        [actions.setLocalFilters]: ({ filters }) => {
            props.setFilters(values.filters)
        },
    }),

    events: ({ actions, props, values }) => ({
        afterMount: () => {
            let sort = (a, b) => a.order - b.order
            let filters = [...(props.defaultFilters.actions || []), ...(props.defaultFilters.events || [])]
            actions.setLocalFilters(filters.sort(sort))
            if (props.setDefaultIfEmpty && filters.length === 0 && values.eventNames) {
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
