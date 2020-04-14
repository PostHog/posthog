import { kea } from 'kea'

import { actionsModel } from '~/models/actionsModel'
import { eventsModel } from '~/models/eventsModel'
import { propertiesModel } from '~/models/propertiesModel'
import { EntityTypes } from '../trendsLogic'

import { groupEvents } from '~/lib/utils'

const mirrorValues = (entities, newKey, valueKey) => {
    let newEntities = entities.map(entity => {
        return {
            ...entity,
            [newKey]: entity[valueKey],
        }
    })
    return newEntities
}

export const entityFilterLogic = kea({
    key: props => props.typeKey,
    connect: {
        values: [propertiesModel, ['properties'], actionsModel, ['actions', 'actionsGrouped'], eventsModel, ['events']],
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
        initializeLocalFilters: true,
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
            () => [selectors.events, selectors.actions],
            (events, actions) => {
                return {
                    [EntityTypes.ACTIONS]: actions,
                    [EntityTypes.EVENTS]: mirrorValues(events, 'id', 'name'),
                }
            },
        ],
        formattedOptions: [
            () => [selectors.events, selectors.actionsGrouped],
            (events, actionsGrouped) => {
                return {
                    [EntityTypes.ACTIONS]: actionsGrouped,
                    [EntityTypes.EVENTS]: groupEvents(events),
                }
            },
        ],
        filters: [
            () => [selectors.allFilters],
            allFilters => {
                return {
                    [EntityTypes.ACTIONS]: allFilters.filter(filter => filter.type == EntityTypes.ACTIONS),
                    [EntityTypes.EVENTS]: allFilters.filter(filter => filter.type == EntityTypes.EVENTS),
                }
            },
        ],
    }),

    listeners: ({ actions, values, props }) => ({
        [actions.updateFilter]: ({ type, index, value }) => {
            let currentfilters = values.allFilters ? [...values.allFilters] : []
            currentfilters[index] = {
                id: value,
                type: type,
            }
            actions.setLocalFilters(currentfilters)
            actions.selectFilter(null)
        },
        [actions.updateFilterMath]: ({ math, index }) => {
            let currentfilters = values.allFilters ? [...values.allFilters] : []
            currentfilters[index].math = math
            actions.setLocalFilters(currentfilters)
        },
        [actions.removeLocalFilter]: ({ index }) => {
            let currentfilters = values.allFilters ? [...values.allFilters] : []
            currentfilters.splice(index, 1)
            actions.setLocalFilters(currentfilters)
        },
        [actions.setLocalFilters]: ({ filters }) => {
            props.setFilters(values.filters)
        },
    }),

    events: ({ actions, props }) => ({
        afterMount: () => {
            let sort = (a, b) => a.order - b.order
            actions.setLocalFilters([...props.defaultFilters.actions, ...props.defaultFilters.events].sort(sort))
        },
    }),
})
