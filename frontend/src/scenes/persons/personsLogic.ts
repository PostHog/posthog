import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { personsLogicType } from './personsLogicType'
import { PersonType } from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

interface PersonPaginatedResponse {
    next: string | null
    previous: string | null
    results: PersonType[]
}

const FILTER_WHITELIST: string[] = ['is_identified', 'search', 'cohort']

export const personsLogic = kea<personsLogicType<PersonPaginatedResponse, PersonType>>({
    connect: {
        actions: [eventUsageLogic, ['reportPersonDetailViewed']],
    },
    actions: {
        setListFilters: (payload) => ({ payload }),
        editProperty: (key: string, newValue?: string | number | boolean | null) => ({ key, newValue }),
        setHasNewKeys: true,
    },
    reducers: {
        listFilters: [
            {} as Record<string, string>,
            {
                setListFilters: (state, { payload }) => ({ ...state, ...payload }),
            },
        ],
        hasNewKeys: [
            false,
            {
                setHasNewKeys: () => true,
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
    listeners: ({ actions, values }) => ({
        deletePersonSuccess: () => {
            toast('Person deleted successfully')
            actions.loadPersons()
            router.actions.push('/persons')
        },
        editProperty: async ({ key, newValue }) => {
            const person = values.person
            if (person) {
                let parsedValue = newValue

                // If the property is a number, store it as a number
                const attemptedParsedNumber = Number(newValue)
                if (!Number.isNaN(attemptedParsedNumber)) {
                    parsedValue = attemptedParsedNumber
                }

                const lowercaseValue = typeof parsedValue === 'string' && parsedValue.toLowerCase()
                if (lowercaseValue === 'true' || lowercaseValue === 'false' || lowercaseValue === 'null') {
                    parsedValue = lowercaseValue === 'true' ? true : lowercaseValue === 'null' ? null : false
                }

                if (!Object.keys(person.properties).includes(key)) {
                    actions.setHasNewKeys()
                    person.properties = { [key]: parsedValue, ...person.properties } // To add property at the top (if new)
                } else {
                    person.properties[key] = parsedValue
                }

                actions.setPerson(person) // To update the UI immediately while the request is being processed
                const response = await api.update(`api/person/${person.id}`, person)
                actions.setPerson(response)
            }
        },
    }),
    loaders: ({ values, actions }) => ({
        persons: [
            { next: null, previous: null, results: [] } as PersonPaginatedResponse,
            {
                loadPersons: async (url: string | null = '') => {
                    const qs = Object.keys(values.listFilters)
                        .filter((key) =>
                            key !== 'is_identified' ? FILTER_WHITELIST.includes(key) : !url?.includes('is_identified')
                        )
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
        person: [
            null as PersonType | null,
            {
                loadPerson: async (id: string): Promise<PersonType | null> => {
                    const response = await api.get(`api/person/?distinct_id=${id}`)
                    if (!response.results.length) {
                        router.actions.push('/404')
                    }
                    const person = response.results[0] as PersonType
                    person && actions.reportPersonDetailViewed(person)
                    return person
                },
                setPerson: (person: PersonType): PersonType => {
                    // Used after merging persons to update the view without an additional request
                    return person
                },
            },
        ],
        deletedPerson: [
            false,
            {
                deletePerson: async () => {
                    if (!values.person) {
                        return false
                    }
                    await api.delete(`api/person/${values.person.id}`)
                    return true
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
        '/persons': ({}, searchParams: Record<string, string>) => {
            actions.setListFilters(searchParams)
            if (!values.persons.results.length && !values.personsLoading) {
                // Initial load
                actions.loadPersons()
            }
        },
        '/person/*': ({ _ }: { _: string }) => {
            actions.loadPerson(_) // underscore contains the wildcard
        },
    }),
})
