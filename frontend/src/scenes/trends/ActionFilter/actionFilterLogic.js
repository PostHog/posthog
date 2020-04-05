import { kea } from 'kea'

import { actionsModel } from '~/models/actionsModel'
import { eventsModel } from '~/models/eventsModel'
import { trendsLogic } from '../trendsLogic'

import { groupActions, groupEvents } from '~/lib/utils'

export const EntityTypes = {
    ACTIONS: 'actions',
    EVENTS: 'events',
    NEW: 'new',
}

const mirrorValues = (entities, newKey, valueKey) => {
    let newEntities = entities.map(entity => {
        return {
            ...entity,
            [newKey]: entity[valueKey],
        }
    })
    return newEntities
}

const formatFilters = (filters, type) => {
    return filters.map(filter => {
        return {
            ...filter,
            type: type,
        }
    })
}

export const entityFilterLogic = kea({
    connect: {
        values: [eventsModel, ['events'], actionsModel, ['actions'], eventsModel, ['events'], trendsLogic, ['filters']],
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
        removeFilter: filter => ({ value: filter.value, type: filter.type, index: filter.index }),
        createNewFilter: () => {},
        setLocalFilters: filters => ({ filters }),
    }),

    events: ({ actions, values }) => ({
        afterMount: () =>
            actions.setLocalFilters([
                ...formatFilters(values.filters.actions, EntityTypes.ACTIONS),
                ...formatFilters(values.filters.events, EntityTypes.EVENTS),
            ]),
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
        formattedFilters: [
            () => [selectors.filters],
            filters => {
                return {
                    [EntityTypes.ACTIONS]: filters.actions,
                    [EntityTypes.EVENTS]: filters.events,
                }
            },
        ],
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
        [actions.updateFilter]: ({ type, index, value }) => {
            let newFilters = values.filters[type]
            // handle if the selected filter is a new filter
            if (values.selectedFilter.type == EntityTypes.NEW) {
                newFilters.push({ id: value })
            } else if (type == values.selectedFilter.type) {
                newFilters[index] = { id: value }
            } else if (type != values.selectedFilter.type) {
                actions.removeFilter({ type: values.selectedFilter.type, value: values.selectedFilter.filter.id })

                let index = newFilters.findIndex(e => e.id == value)
                if (index >= 0) newFilters[index] = { id: value }
                else if (newFilters.length > 0) newFilters.push({ id: value })
                else newFilters = [{ id: value }]
            }

            actions.setFilters({ [type]: newFilters })

            let currentfilters = [...values.allFilters]
            currentfilters[index] = {
                id: value,
                type: type,
            }
            actions.setLocalFilters(currentfilters)
            actions.selectFilter(null)
        },
        [actions.updateFilterMath]: ({ type, value, math, index }) => {
            // parent logic change
            let newFilters = [...values.formattedFilters[type]]
            let target = newFilters.findIndex(e => e.id == value)
            newFilters[target].math = math
            actions.setFilters({ [type]: newFilters })

            // local changes
            let currentfilters = [...values.allFilters]
            currentfilters[index].math = math
            actions.setLocalFilters(currentfilters)
        },
        [actions.removeFilter]: ({ type, value, index }) => {
            let newFilters = [...values.formattedFilters[type]]
            let target = newFilters.findIndex(e => e.id == value)
            newFilters.splice(target, 1)
            actions.setFilters({ [type]: newFilters })

            let currentfilters = [...values.allFilters]
            currentfilters.splice(index, 1)
            actions.setLocalFilters(currentfilters)
        },
    }),
})
