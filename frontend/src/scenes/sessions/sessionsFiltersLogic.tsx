import { kea } from 'kea'
import { sessionsFiltersLogicType } from 'types/scenes/sessions/sessionsFiltersLogicType'
import { SessionsPropertyFilter } from '~/types'

type FilterSelector = number | 'new'

export const sessionsFiltersLogic = kea<sessionsFiltersLogicType<SessionsPropertyFilter, FilterSelector>>({
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
    listeners: ({ actions, values }) => ({
        dropdownSelected: ({ type, id, label }) => {
            if (values.openFilter !== null) {
                if (type === 'action_type' || type === 'cohort') {
                    actions.updateFilter({ type, value: id, key: 'id', label }, values.openFilter)
                }
            }
        },
    }),
})
