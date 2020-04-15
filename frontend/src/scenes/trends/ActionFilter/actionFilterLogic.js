import { kea } from 'kea'

import { actionsModel } from '~/models/actionsModel'
import { EntityTypes } from '../trendsLogic'

import { groupEvents } from '~/lib/utils'
import { userLogic } from 'scenes/userLogic'

const mirrorValues = (entities, newKey) => {
    let newEntities = entities.map(entity => {
        return {
            ...entity,
            [newKey]: entity,
        }
    })
    return newEntities
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
        setLocalFilters: filters => ({ filters }),
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
                    [EntityTypes.EVENTS]: events,
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
            actions.setLocalFilters(
                [...(props.defaultFilters.actions || []), ...(props.defaultFilters.events || [])].sort(sort)
            )
        },
    }),
})
