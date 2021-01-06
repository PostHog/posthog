import { kea } from 'kea'
import { sessionsFiltersLogicType } from 'types/scenes/sessions/sessionsFiltersLogicType'
import { SessionsPropertyFilter } from '~/types'

type NewFilter = 'new'
type FilterSelector = number | NewFilter

export const sessionsFiltersLogic = kea<sessionsFiltersLogicType<SessionsPropertyFilter>>({
    actions: () => ({
        openFilterSelect: (selector: FilterSelector) => ({ selector }),
        closeFilterSelect: true,
        updateFilter: (property: SessionsPropertyFilter, selector: FilterSelector) => ({ property, selector }),
        removeFilter: (selector: number) => ({ selector }),
        dropdownSelected: (type: SessionsPropertyFilter['type'], id: string) => ({ type, id })
    }),
    reducers: {
        filters: [
            [] as Array<SessionsPropertyFilter>,
            {
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
                    newState.splice(selector)
                    return newState
                }
            }
        ],
        openFilter: [
            null as null | FilterSelector,
            {
                openFilterSelect: (_, { selector }) => selector,
                updateFilter: () => null,
                closeFilterSelect: () => null
            }
        ]
    },
    selectors: {
        displayedFilters: [
            (s) => [s.filters],
            (filters: Array<SessionsPropertyFilter>) => {
                const groups: Record<string, Array<{ item: SessionsPropertyFilter, selector: number }>> = {}
                filters.forEach((item, selector) => {
                    groups[item.type] = groups[item.type] || []
                    groups[item.type].push({ item, selector })
                })
                return groups
            }
        ]
    },
    listeners: ({ actions, values }) => ({
        dropdownSelected: ({ type, id }) => {
            if (values.openFilter) {
                // let property: SessionsPropertyFilter
                // actions.updateFilter(property, values.openFilter)
            }
        }
    })
})
