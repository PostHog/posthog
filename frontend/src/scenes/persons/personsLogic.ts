import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { personsLogicType } from 'types/scenes/persons/personsLogicType'
import { PersonType } from '~/types'

interface PersonPaginatedResponse {
    next: string | null
    previous: string | null
    results: PersonType[]
}

const FILTER_WHITELIST: string[] = ['is_identified', 'search', 'cohort']

export const personsLogic = kea<personsLogicType<PersonPaginatedResponse>>({
    actions: {
        setListFilters: (payload) => ({ payload }),
    },
    reducers: {
        listFilters: [
            {} as Record<string, string>,
            {
                setListFilters: (state, { payload }) => ({ ...state, ...payload }),
            },
        ],
    },
    selectors: {
        exampleEmail: [
            (s) => [s.persons],
            (persons: PersonPaginatedResponse): string => {
                const match = persons && persons.results.find((person) => person.properties?.email)
                return match?.properties?.email || 'example@gmail.com'
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
                    const dest = `${url || 'api/person/'}${qs.length ? '?' + qs.join('&') : ''}`
                    return await api.get(dest)
                },
            },
        ],
    }),
    actionToUrl: ({ values, props }) => ({
        setListFilters: () => {
            if (props.updateURL && router.values.location.pathname.indexOf('/persons') > -1) {
                return ['/persons', values.listFilters]
            }
        },
    }),
    urlToAction: ({ actions, values }) => ({
        '/persons': (_, searchParams: Record<string, string>) => {
            actions.setListFilters(searchParams)
            if (!values.persons.results.length && !values.personsLoading) {
                // Initial load
                actions.loadPersons()
            }
        },
    }),
})
