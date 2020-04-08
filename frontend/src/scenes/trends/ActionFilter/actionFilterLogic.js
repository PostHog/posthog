import { kea } from 'kea'

import { actionsModel } from '~/models/actionsModel'
import { eventsModel } from '~/models/eventsModel'
import { trendsLogic, EntityTypes } from '../trendsLogic'

import { groupActions, groupEvents } from '~/lib/utils'

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
    connect: {
        values: [eventsModel, ['events'], actionsModel, ['actions'], trendsLogic, ['filters']],
        actions: [trendsLogic, ['setFilters']],
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
        removeFilter: filter => ({ value: filter.value, type: filter.type, index: filter.index }),
        createNewFilter: true,
        setLocalFilters: filters => ({ filters }),
        initializeLocalFilters: true,
    }),

    events: ({ actions }) => ({
        afterMount: actions.initializeLocalFilters,
    }),

    reducers: ({ actions }) => ({
        selectedFilter: [
            null,
            {
                [actions.selectFilter]: (state, { filter }) => filter,
            },
        ],
        allFilters: [
            [],
            {
                [actions.setLocalFilters]: (state, { filters }) => filters,
                [actions.createNewFilter]: state => [...state, { id: null, type: EntityTypes.NEW }],
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
            () => [selectors.events, selectors.actions],
            (events, actions) => {
                return {
                    [EntityTypes.ACTIONS]: groupActions(actions),
                    [EntityTypes.EVENTS]: groupEvents(events),
                }
            },
        ],
    }),

    listeners: ({ actions, values }) => ({
        [actions.initializeLocalFilters]: () => {
            actions.setLocalFilters([...(values.filters.actions || []), ...(values.filters.events || [])])
        },
        [actions.updateFilter]: ({ type, index, value }) => {
            let newFilters = values.filters[type]
            newFilters.push({ id: value, type })

            // if the types are the same update together otherwise can dispatch to action
            if (type == values.selectedFilter.type) {
                let target = newFilters.findIndex(e => e.id == values.selectedFilter.filter.id)
                newFilters.splice(target, 1)
            } else {
                actions.removeFilter({ type: values.selectedFilter.type, value: values.selectedFilter.filter.id })
            }

            actions.setFilters({ [type]: newFilters })

            let currentfilters = values.allFilters ? [...values.allFilters] : []
            currentfilters[index] = {
                id: value,
                type: type,
            }
            actions.setLocalFilters(currentfilters)
            actions.selectFilter(null)
        },
        [actions.updateFilterMath]: ({ type, value, math, index }) => {
            // parent logic change
            let newFilters = values.filters[type] ? [...values.filters[type]] : []
            let target = newFilters.findIndex(e => e.id == value)
            newFilters[target].math = math
            actions.setFilters({ [type]: newFilters })

            // local changes
            let currentfilters = values.allFilters ? [...values.allFilters] : []
            currentfilters[index].math = math
            actions.setLocalFilters(currentfilters)
        },
        [actions.removeLocalFilter]: ({ type, value, index }) => {
            actions.removeFilter({ type, value })
            let currentfilters = values.allFilters ? [...values.allFilters] : []
            currentfilters.splice(index, 1)
            actions.setLocalFilters(currentfilters)
        },
        [actions.removeFilter]: ({ type, value }) => {
            let newFilters = values.filters[type] ? [...values.filters[type]] : []
            let target = newFilters.findIndex(e => e.id == value)
            newFilters.splice(target, 1)
            actions.setFilters({ [type]: newFilters })
        },
    }),
})
