import { kea } from 'kea'
import api from 'lib/api'
import { personsLogicType } from 'types/scenes/persons/personsLogicType'
import { PersonType } from '~/types'

interface PersonPaginatedResponse {
    next: string | null
    previous: string | null
    results: PersonType[]
}

const FILTER_WHITELIST: string[] = ['is_identified', 'search']

export const personsLogic = kea<personsLogicType<PersonPaginatedResponse>>({
    actions: {
        setListFilters: (payload) => ({ payload }),
        setCohort: (cohort) => ({ cohort }),
    },
    reducers: {
        listFilters: [
            {} as Record<string, string>,
            {
                setListFilters: (state, { payload }) => ({ ...state, ...payload }),
            },
        ],
        cohort: [
            null as number | null,
            {
                setCohort: (_, { cohort }) => cohort,
            },
        ],
    },
    loaders: ({ values }) => ({
        persons: [
            { next: null, previous: null, results: [] } as PersonPaginatedResponse,
            {
                loadPersons: async (url: string | null = '') => {
                    const qs = Object.keys(values.listFilters)
                        .filter((key) => FILTER_WHITELIST.includes(key))
                        .reduce(function (result, key) {
                            const value = values.listFilters[key]
                            if (value !== undefined && value !== null) {
                                result.push(`${key}=${value}`)
                            }
                            return result
                        }, [] as string[])
                    if (values.cohort) qs.push(`cohort=${values.cohort}`)
                    const dest = `${url || 'api/person/'}${qs.length ? '?' + qs.join('&') : ''}`
                    return await api.get(dest)
                },
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadPersons()
        },
    }),
    actionToUrl: ({ values }) => ({
        setListFilters: () => {
            return ['/persons', values.listFilters]
        },
    }),
    urlToAction: ({ actions }) => ({
        '/persons': (_, searchParams: Record<string, string>) => {
            actions.setListFilters(searchParams)
        },
    }),
})
