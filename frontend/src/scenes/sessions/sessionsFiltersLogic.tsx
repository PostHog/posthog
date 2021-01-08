import { kea } from 'kea'
import api from 'lib/api'
import { sessionsFiltersLogicType } from 'types/scenes/sessions/sessionsFiltersLogicType'
import { SessionsPropertyFilter } from '~/types'

type FilterSelector = number | 'new'

export interface PersonProperty {
    name: string
    count: number
}

export const sessionsFiltersLogic = kea<
    sessionsFiltersLogicType<SessionsPropertyFilter, FilterSelector, PersonProperty>
>({
    actions: () => ({
        openFilterSelect: (selector: FilterSelector) => ({ selector }),
        closeFilterSelect: true,
        setAllFilters: (filters: Array<SessionsPropertyFilter>) => ({ filters }),
        updateFilter: (property: SessionsPropertyFilter, selector: FilterSelector) => ({ property, selector }),
        removeFilter: (selector: number) => ({ selector }),
        dropdownSelected: (type: SessionsPropertyFilter['type'], id: string | number, label: string) => ({
            type,
            id,
            label,
        }),
    }),
    reducers: {
        filters: [
            [] as Array<SessionsPropertyFilter>,
            {
                setAllFilters: (_, { filters }) => filters,
                updateFilter: (state, { property, selector }) => {
                    if (selector === 'new') {
                        return [...state, property]
                    }
                    const newState = [...state]
                    newState[selector] = property
                    return newState
                },
                removeFilter: (state, { selector }) => {
                    const newState = [...state]
                    newState.splice(selector, 1)
                    return newState
                },
            },
        ],
        openFilter: [
            null as null | FilterSelector,
            {
                openFilterSelect: (_, { selector }) => selector,
                updateFilter: () => null,
                closeFilterSelect: () => null,
            },
        ],
    },
    selectors: {
        displayedFilters: [
            (s) => [s.filters],
            (filters: Array<SessionsPropertyFilter>) => {
                const groups: Record<string, Array<{ item: SessionsPropertyFilter; selector: number }>> = {}
                filters.forEach((item, selector) => {
                    groups[item.type] = groups[item.type] || []
                    groups[item.type].push({ item, selector })
                })
                return groups
            },
        ],
    },
    loaders: () => ({
        personProperties: [
            [] as Array<PersonProperty>,
            {
                loadPersonProperties: async (): Promise<Array<PersonProperty>> =>
                    await api.get('api/person/properties'),
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        dropdownSelected: ({ type, id, label }) => {
            if (values.openFilter !== null) {
                if (type === 'action_type' || type === 'event_type' || type === 'cohort') {
                    actions.updateFilter({ type, key: 'id', value: id, label }, values.openFilter)
                } else if (type === 'person') {
                    actions.updateFilter({ type, key: id, value: null, label, operator: 'exact' }, values.openFilter)
                } else if (type === 'recording' && id === 'duration') {
                    actions.updateFilter({ type, key: id, value: 0, label, operator: 'gt' }, values.openFilter)
                }
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadPersonProperties()
        },
    }),
})
