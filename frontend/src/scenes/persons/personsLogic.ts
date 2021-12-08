import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { personsLogicType } from './personsLogicType'
import { CohortType, PersonsTabType, PersonType, AnyPropertyFilter, Breadcrumb } from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'
import { teamLogic } from 'scenes/teamLogic'
import { toParams } from 'lib/utils'
import { asDisplay } from 'scenes/persons/PersonHeader'

interface PersonPaginatedResponse {
    next: string | null
    previous: string | null
    results: PersonType[]
}

interface Filters {
    properties?: AnyPropertyFilter[]
    search?: string
    cohort?: number
}

export interface PersonLogicProps {
    cohort?: number | 'new' | 'personsModalNew'
    syncWithUrl?: boolean
    urlId?: string
}

export const personsLogic = kea<personsLogicType<Filters, PersonLogicProps, PersonPaginatedResponse>>({
    props: {} as PersonLogicProps,
    key: (props) => {
        if (!props.cohort && !props.syncWithUrl) {
            throw new Error(`personsLogic must be initialized with props.cohort or props.syncWithUrl`)
        }
        return props.cohort ? `cohort_${props.cohort}` : 'scene'
    },
    path: (key) => ['scenes', 'persons', 'personsLogic', key],
    connect: {
        actions: [eventUsageLogic, ['reportPersonDetailViewed']],
        values: [teamLogic, ['currentTeam']],
    },
    actions: {
        setPerson: (person: PersonType) => ({ person }),
        loadPerson: (id: string) => ({ id }),
        loadPersons: (url: string | null = '') => ({ url }),
        setListFilters: (payload: Filters) => ({ payload }),
        editProperty: (key: string, newValue?: string | number | boolean | null) => ({ key, newValue }),
        setHasNewKeys: true,
        navigateToCohort: (cohort: CohortType) => ({ cohort }),
        navigateToTab: (tab: PersonsTabType) => ({ tab }),
        setSplitMergeModalShown: (shown: boolean) => ({ shown }),
    },
    reducers: {
        listFilters: [
            {} as Filters,
            {
                setListFilters: (state, { payload }) => {
                    const newFilters = { ...state, ...payload }
                    if (newFilters.properties?.length === 0) {
                        delete newFilters['properties']
                    }
                    return newFilters
                },
            },
        ],
        hasNewKeys: [
            false,
            {
                setHasNewKeys: () => true,
            },
        ],
        activeTab: [
            null as PersonsTabType | null,
            {
                navigateToTab: (_, { tab }) => tab,
            },
        ],
        splitMergeModalShown: [
            false,
            {
                setSplitMergeModalShown: (_, { shown }) => shown,
            },
        ],
        persons: {
            setPerson: (state, { person }) => ({
                ...state,
                results: state.results.map((p) => (p.id === person.id ? person : p)),
            }),
        },
    },
    selectors: {
        showSessionRecordings: [
            (s) => [s.currentTeam],
            (currentTeam): boolean => {
                return !!currentTeam?.session_recording_opt_in
            },
        ],
        currentTab: [
            (s) => [s.activeTab, s.showSessionRecordings],
            (activeTab, showSessionRecordings) => {
                // Ensure the activeTab reflects a valid tab given the available tabs
                if (!activeTab) {
                    return showSessionRecordings ? PersonsTabType.SESSION_RECORDINGS : PersonsTabType.EVENTS
                }
                if (activeTab === PersonsTabType.SESSION_RECORDINGS && !showSessionRecordings) {
                    return PersonsTabType.EVENTS
                }
                return activeTab
            },
        ],
        breadcrumbs: [
            (s) => [s.person, router.selectors.location],
            (person, location): Breadcrumb[] => {
                const showPerson = person && location.pathname.match(/\/person\/.+/)
                const breadcrumbs: Breadcrumb[] = [
                    {
                        name: 'Persons',
                        path: urls.persons(),
                    },
                ]
                if (showPerson) {
                    breadcrumbs.push({
                        name: asDisplay(person),
                    })
                }
                return breadcrumbs
            },
        ],
    },
    listeners: ({ actions, values }) => ({
        deletePersonSuccess: () => {
            toast('Person deleted successfully')
            actions.loadPersons()
            router.actions.push(urls.persons())
        },
        editProperty: async ({ key, newValue }) => {
            const person = values.person

            if (person) {
                let parsedValue = newValue

                // Instrumentation stuff
                let action: 'added' | 'updated' | 'removed'
                const oldPropertyType = person.properties[key] === null ? 'null' : typeof person.properties[key]
                let newPropertyType: string = typeof newValue

                // If the property is a number, store it as a number
                const attemptedParsedNumber = Number(newValue)
                if (!Number.isNaN(attemptedParsedNumber) && typeof newValue !== 'boolean') {
                    parsedValue = attemptedParsedNumber
                    newPropertyType = 'number'
                }

                const lowercaseValue = typeof parsedValue === 'string' && parsedValue.toLowerCase()
                if (lowercaseValue === 'true' || lowercaseValue === 'false' || lowercaseValue === 'null') {
                    parsedValue = lowercaseValue === 'true' ? true : lowercaseValue === 'null' ? null : false
                    newPropertyType = parsedValue !== null ? 'boolean' : 'null'
                }

                if (!Object.keys(person.properties).includes(key)) {
                    actions.setHasNewKeys()
                    person.properties = { [key]: parsedValue, ...person.properties } // To add property at the top (if new)
                    action = 'added'
                } else {
                    person.properties[key] = parsedValue
                    action = parsedValue !== undefined ? 'updated' : 'removed'
                }

                actions.setPerson(person) // To update the UI immediately while the request is being processed
                const response = await api.update(`api/person/${person.id}`, person)
                actions.setPerson(response)

                eventUsageLogic.actions.reportPersonPropertyUpdated(
                    action,
                    Object.keys(person.properties).length,
                    oldPropertyType,
                    newPropertyType
                )
            }
        },
        navigateToCohort: ({ cohort }) => {
            router.actions.push(urls.cohort(cohort.id))
        },
    }),
    loaders: ({ values, actions }) => ({
        persons: [
            { next: null, previous: null, results: [] } as PersonPaginatedResponse,
            {
                loadPersons: async ({ url }) => {
                    if (!url) {
                        url = `api/person/?${toParams(values.listFilters)}`
                    }
                    return await api.get(url)
                },
            },
        ],
        person: [
            null as PersonType | null,
            {
                loadPerson: async ({ id }): Promise<PersonType | null> => {
                    const response = await api.get(`api/person/?distinct_id=${id}`)
                    if (!response.results.length) {
                        router.actions.push(urls.notFound())
                    }
                    const person = response.results[0] as PersonType
                    person && actions.reportPersonDetailViewed(person)
                    return person
                },
                setPerson: ({ person }): PersonType => {
                    // Used after merging persons to update the view without an additional request
                    return person
                },
            },
        ],
        cohorts: [
            null as CohortType[] | null,
            {
                loadCohorts: async (): Promise<CohortType[] | null> => {
                    const response = await api.get(`api/person/cohorts/?person_id=${values.person?.id}`)
                    return response.results
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
            if (props.syncWithUrl && router.values.location.pathname.indexOf('/persons') > -1) {
                return ['/persons', values.listFilters, undefined, { replace: true }]
            }
        },
        navigateToTab: () => {
            if (props.syncWithUrl && router.values.location.pathname.indexOf('/person') > -1) {
                return [
                    router.values.location.pathname,
                    router.values.searchParams,
                    {
                        ...router.values.hashParams,
                        activeTab: values.activeTab,
                    },
                ]
            }
        },
    }),
    urlToAction: ({ actions, values, props }) => ({
        '/persons': ({}, searchParams) => {
            if (props.syncWithUrl) {
                actions.setListFilters(searchParams)
                if (!values.persons.results.length && !values.personsLoading) {
                    // Initial load
                    actions.loadPersons()
                }
            }
        },
        '/person/*': ({ _: person }, { sessionRecordingId }, { activeTab }) => {
            if (props.syncWithUrl) {
                if (sessionRecordingId) {
                    if (values.showSessionRecordings) {
                        actions.navigateToTab(PersonsTabType.SESSION_RECORDINGS)
                    } else {
                        actions.navigateToTab(PersonsTabType.EVENTS)
                    }
                } else if (activeTab && values.activeTab !== activeTab) {
                    actions.navigateToTab(activeTab as PersonsTabType)
                }

                if (person) {
                    actions.loadPerson(person) // underscore contains the wildcard
                }
            }
        },
    }),
    events: ({ props, actions }) => ({
        afterMount: () => {
            if (props.cohort && typeof props.cohort === 'number') {
                actions.setListFilters({ cohort: props.cohort })
                actions.loadPersons()
            }
        },
    }),
})
