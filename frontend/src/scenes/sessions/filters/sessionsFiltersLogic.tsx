import { kea } from 'kea'
import equal from 'fast-deep-equal'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { SESSIONS_WITH_RECORDINGS_FILTER } from 'scenes/sessions/filters/constants'
import { sessionsFiltersLogicType } from 'types/scenes/sessions/filters/sessionsFiltersLogicType'
import { SessionsPropertyFilter } from '~/types'

type FilterSelector = number | 'new'

export interface PersonProperty {
    name: string
    count: number
}

export interface SavedFilter {
    id: string | number
    name: string
    filters: {
        properties: Array<SessionsPropertyFilter>
    }
}

type FilterPropertyType = SessionsPropertyFilter['type']

export const sessionsFiltersLogic = kea<
    sessionsFiltersLogicType<SessionsPropertyFilter, FilterSelector, PersonProperty, SavedFilter, FilterPropertyType>
>({
    actions: () => ({
        openFilterSelect: (selector: FilterSelector) => ({ selector }),
        closeFilterSelect: true,
        setAllFilters: (filters: Array<SessionsPropertyFilter>) => ({ filters }),
        updateFilter: (property: SessionsPropertyFilter, selector: FilterSelector) => ({ property, selector }),
        removeFilter: (selector: number) => ({ selector }),
        dropdownSelected: (type: FilterPropertyType, id: string | number, label: string) => ({
            type,
            id,
            label,
        }),
        createSessionsFilter: (name: string) => ({ name }),
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
        savedFilters: [
            (s) => [s.customFilters],
            (customFilters): Array<SavedFilter> => [
                {
                    id: 'all',
                    name: 'All sessions',
                    filters: { properties: [] },
                },
                {
                    id: 'withrecordings',
                    name: 'Sessions with recordings',
                    filters: { properties: [SESSIONS_WITH_RECORDINGS_FILTER] },
                },
                ...customFilters,
            ],
        ],
        activeFilter: [
            (s) => [s.filters, s.savedFilters],
            (filters: Array<SessionsPropertyFilter>, savedFilters: Array<SavedFilter>): SavedFilter | null =>
                savedFilters.filter((savedFilter) => equal(savedFilter.filters.properties, filters))[0],
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
        customFilters: [
            [] as Array<SavedFilter>,
            {
                loadCustomFilters: async (): Promise<Array<SavedFilter>> => {
                    const { results } = await api.get('api/sessions_filter')
                    return results
                },
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
        createSessionsFilter: async ({ name }) => {
            await api.create('api/sessions_filter', { name, filters: { properties: values.filters } })

            actions.loadCustomFilters()
            toast('Filter saved')
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadPersonProperties()
            actions.loadCustomFilters()
        },
    }),
})
