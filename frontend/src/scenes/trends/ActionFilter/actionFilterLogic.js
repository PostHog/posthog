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

export const entityFilterLogic = kea({
    connect: {
        values: [eventsModel, ['events'], actionsModel, ['actions'], eventsModel, ['events'], trendsLogic, ['filters']],
        actions: [trendsLogic, ['setFilters']],
    },

    actions: () => ({
        selectFilter: filter => ({ filter }),
        updateFilterMath: filter => ({ type: filter.type, value: filter.value, math: filter.math }),
        updateFilter: filter => ({ type: filter.type, index: filter.index, value: filter.value }),
        removeFilter: filter => ({ value: filter.value, type: filter.type, index: filter.index }),
        createNewFilter: () => {},
        removeNewFilter: () => {},
    }),

    reducers: ({ actions }) => ({
        selectedFilter: [
            null,
            {
                [actions.selectFilter]: (state, { filter }) => filter,
            },
        ],
        newFilters: [
            [],
            {
                [actions.createNewFilter]: state => [...state, { id: null }],
                [actions.removeNewFilter]: state => {
                    let newState = [...state]
                    newState.pop()
                    return newState
                },
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
                    [EntityTypes.EVENTS]: events,
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

    listeners: ({ actions, values, props }) => ({
        [actions.updateFilter]: ({ type, index, value }) => {
            // handle if the selected filter is a new filter
            if (values.selectedFilter.type == EntityTypes.NEW) {
                let newFilters = values.filters[type]
                newFilters.push({ id: value })
                actions.setFilters({ [type]: newFilters })
                actions.removeNewFilter()

                // changing the filter to another filter of the same type
            } else if (type == values.selectedFilter.type) {
                let newFilters = values.filters[type]
                newFilters[index] = { id: value }
                actions.setFilters({ [type]: newFilters })

                // Changing the filter to a different filter type
                // Delete the currently selected one and add the other one
            } else if (type != values.selectedFilter.type) {
                console.log(values.selectedFilter)
                actions.removeFilter({ type: values.selectedFilter.type, value: values.selectedFilter.filter.id })
                let newFilters = values.filters[type]

                let index = newFilters.findIndex(e => e.id == value)

                if (index >= 0) newFilters[index] = { id: value }
                else if (newFilters.length > 0) newFilters.push({ id: value })
                else newFilters = [{ id: value }]

                actions.setFilters({ [type]: newFilters })
            }
            actions.selectFilter(null)
        },
        [actions.updateFilterMath]: ({ type, value, math }) => {
            let newFilters = values.filters[type]
            let target = newFilters.findIndex(e => e.id == value)
            newFilters[target].math = math
            actions.setFilters({ [type]: newFilters })
        },
        [actions.removeFilter]: ({ type, value }) => {
            if (type == EntityTypes.NEW) {
                actions.removeNewFilter()
                return
            }
            let newFilters = values.filters[type]
            let target = newFilters.findIndex(e => e.id == value)
            newFilters.splice(target, 1)
            actions.setFilters({ [type]: newFilters })
        },
    }),
})
