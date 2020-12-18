import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { personsLogicType } from 'types/scenes/persons/personsLogicType'
import { PersonType } from '~/types'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import posthog from 'posthog-js'

interface PersonPaginatedResponse {
    next: string | null
    previous: string | null
    results: PersonType[]
}

const keyMappingKeys = Object.keys(keyMapping.event)

const FILTER_WHITELIST: string[] = ['is_identified', 'search', 'cohort']

export const personsLogic = kea<personsLogicType<PersonPaginatedResponse>>({
    actions: {
        setListFilters: (payload) => ({ payload }),
        editProperty: (key, newValue) => ({ key, newValue }),
        reportUsage: () => {},
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
    listeners: ({ actions, values }) => ({
        deletePersonSuccess: () => {
            toast('Person deleted successfully')
            actions.loadPersons()
            router.actions.push('/persons')
        },
        editProperty: async ({ key, newValue }) => {
            const person = values.person
            person.properties[key] = newValue
            actions.setPerson(person) // To update the UI immediately while the request is being processed
            const response = await api.update(`api/person/${person.id}`, person)
            actions.setPerson(response)
        },
        reportUsage: async (_, breakpoint) => {
            await breakpoint(5000)

            let custom_properties_count = 0
            let posthog_properties_count = 0
            for (const prop of Object.keys(values.person.properties)) {
                if (keyMappingKeys.includes(prop)) {
                    posthog_properties_count += 1
                } else {
                    custom_properties_count += 1
                }
            }

            const properties = {
                properties_count: Object.keys(values.person.properties).length,
                is_identified: values.person.is_identified,
                has_email: !!values.person.properties.email,
                has_name: !!values.person.properties.name,
                custom_properties_count,
                posthog_properties_count,
            }
            posthog.capture('person viewed', properties)
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
                loadPerson: async (id: string): Promise<PersonType> => {
                    const response = await api.get(`api/person/?distinct_id=${id}`)
                    if (!response.results.length) {
                        router.actions.push('/404')
                    }
                    actions.reportUsage()
                    return response.results[0]
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
        '/persons': (_, searchParams: Record<string, string>) => {
            actions.setListFilters(searchParams)
            if (!values.persons.results.length && !values.personsLoading) {
                // Initial load
                actions.loadPersons()
            }
        },
        '/person/:id': ({ id }: { id: string }) => {
            actions.loadPerson(id)
        },
    }),
})
