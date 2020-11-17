import { kea } from 'kea'
import api from 'lib/api'
import { personsLogicType } from 'types/scenes/persons/personsLogicType'
import { PersonType } from '~/types'

interface PersonPaginatedResponse {
    next: string | null
    previous: string | null
    results: PersonType[]
}

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
                    const qs = Object.keys(values.listFilters).map((key) => `${key}=${values.listFilters[key]}`)
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
    actionToUrl: () => ({
        setListFilters: ({ payload }: { payload: Record<string, any> }) => {
            return ['/persons', payload]
        },
    }),
    urlToAction: ({ actions }) => ({
        '/persons': (_, searchParams: Record<string, string>) => {
            console.log(searchParams)
            actions.setListFilters(searchParams)
        },
    }),
})
