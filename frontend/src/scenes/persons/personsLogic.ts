import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import type { personsLogicType } from './personsLogicType'
import { AnyPropertyFilter, Breadcrumb, CohortType, ExporterFormat, PersonsTabType, PersonType } from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'
import { teamLogic } from 'scenes/teamLogic'
import { convertPropertyGroupToProperties, toParams } from 'lib/utils'
import { asDisplay } from 'scenes/persons/PersonHeader'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { lemonToast } from 'lib/components/lemonToast'
import { triggerExport, TriggerExportProps } from 'lib/components/ExportButton/exporter'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export interface PersonPaginatedResponse {
    next: string | null
    previous: string | null
    results: PersonType[]
}

export interface PersonFilters {
    properties?: AnyPropertyFilter[]
    search?: string
    cohort?: number
}

export interface PersonLogicProps {
    cohort?: number | 'new'
    syncWithUrl?: boolean
    urlId?: string
}

export const personsLogic = kea<personsLogicType>({
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
        setPerson: (person: PersonType | null) => ({ person }),
        loadPerson: (id: string) => ({ id }),
        loadPersons: (url: string | null = '') => ({ url }),
        setListFilters: (payload: PersonFilters) => ({ payload }),
        editProperty: (key: string, newValue?: string | number | boolean | null) => ({ key, newValue }),
        deleteProperty: (key: string) => ({ key }),
        navigateToCohort: (cohort: CohortType) => ({ cohort }),
        navigateToTab: (tab: PersonsTabType) => ({ tab }),
        setSplitMergeModalShown: (shown: boolean) => ({ shown }),
        exportCsv: true,
    },
    reducers: {
        listFilters: [
            {} as PersonFilters,
            {
                setListFilters: (state, { payload }) => {
                    const newFilters = { ...state, ...payload }
                    if (newFilters.properties?.length === 0) {
                        delete newFilters['properties']
                    }
                    if (newFilters.properties) {
                        newFilters.properties = convertPropertyGroupToProperties(
                            newFilters.properties.filter(isValidPropertyFilter)
                        )
                    }
                    return newFilters
                },
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
                results: state.results.map((p) => (person && p.id === person.id ? person : p)),
            }),
        },
        person: {
            loadPerson: () => null,
            setPerson: (_, { person }): PersonType | null => person,
        },
    },
    selectors: () => ({
        cohortId: [() => [(_, props) => props.cohort], (cohort: PersonLogicProps['cohort']) => cohort],
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
                if (activeTab === PersonsTabType.SESSION_RECORDINGS && !showSessionRecordings) {
                    return PersonsTabType.EVENTS
                }
                return activeTab || PersonsTabType.PROPERTIES
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
        exportUrl: [
            (s) => [s.listFilters, (_, { cohort }) => cohort],
            (listFilters, cohort): string =>
                cohort ? `/api/cohort/${cohort}/persons.csv?` : api.person.determineCSVUrl(listFilters),
        ],

        exporterProps: [
            (s) => [s.listFilters, (_, { cohort }) => cohort],
            (listFilters, cohort): TriggerExportProps[] => [
                {
                    export_format: ExporterFormat.CSV,
                    export_context: {
                        path: (cohort ? `/api/cohort/${cohort}/persons` : `api/person/`) + `?${toParams(listFilters)}`,
                    },
                },
            ],
        ],
    }),
    listeners: ({ actions, values, props }) => ({
        deletePersonSuccess: () => {
            // The deleted person's distinct IDs won't be usable until the person disappears from PersonManager's LRU.
            // This can take up to an hour. Until then, the plugin server won't know to regenerate the person.
            lemonToast.success('Person deleted. Their ID(s) will be usable again in an hour or so')
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
                    person.properties = { [key]: parsedValue, ...person.properties } // To add property at the top (if new)
                    action = 'added'
                } else {
                    person.properties[key] = parsedValue
                    action = 'updated'
                }

                actions.setPerson({ ...person }) // To update the UI immediately while the request is being processed
                // :KLUDGE: Person properties are updated asynchronosly in the plugin server - the response won't reflect
                //      the 'updated' properties yet.
                await api.update(`api/person/${person.id}`, person)
                lemonToast.success(`Person property ${action}`)

                eventUsageLogic.actions.reportPersonPropertyUpdated(
                    action,
                    Object.keys(person.properties).length,
                    oldPropertyType,
                    newPropertyType
                )
            }
        },
        deleteProperty: async ({ key }) => {
            const person = values.person

            if (person) {
                const updatedProperties = { ...person.properties }
                delete updatedProperties[key]

                actions.setPerson({ ...person, properties: updatedProperties })
                await api.create(`api/person/${person.id}/delete_property`, { $unset: key })
                lemonToast.success(`Person property deleted`)

                eventUsageLogic.actions.reportPersonPropertyUpdated('removed', 1, undefined, undefined)
            }
        },
        navigateToCohort: ({ cohort }) => {
            router.actions.push(urls.cohort(cohort.id))
        },
        exportCsv: () => {
            if (!!featureFlagLogic.values.featureFlags[FEATURE_FLAGS.ASYNC_EXPORT_CSV_FOR_LIVE_EVENTS]) {
                const path = props.cohort
                    ? `api/cohort/${props.cohort}/persons/?${toParams(values.listFilters)}`
                    : `api/person/?${toParams(values.listFilters)}`

                triggerExport({
                    export_format: ExporterFormat.CSV,
                    export_context: {
                        path,
                    },
                })
            } else {
                lemonToast.success('The export is starting. It should finish soon')
                window.location.href = values.exportUrl
            }
        },
    }),
    loaders: ({ values, actions, props }) => ({
        persons: [
            { next: null, previous: null, results: [] } as PersonPaginatedResponse,
            {
                loadPersons: async ({ url }) => {
                    if (!url) {
                        if (props.cohort) {
                            url = `api/cohort/${props.cohort}/persons/?${toParams(values.listFilters)}`
                        } else {
                            url = `api/person/?${toParams(values.listFilters)}`
                        }
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
                    const person = response.results[0] || (null as PersonType | null)
                    if (person) {
                        actions.reportPersonDetailViewed(person)
                    }
                    return person
                },
            },
        ],
        cohorts: [
            null as CohortType[] | null,
            {
                loadCohorts: async (): Promise<CohortType[] | null> => {
                    if (!values.person?.id) {
                        return null
                    }
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
                const searchParams = { ...router.values.searchParams }

                if (values.activeTab !== PersonsTabType.HISTORY) {
                    delete searchParams['page']
                }

                return [
                    router.values.location.pathname,
                    searchParams,
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
        '/person/*': ({ _: rawPersonDistinctId }, { sessionRecordingId }, { activeTab }) => {
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

                if (!activeTab && values.activeTab && values.activeTab !== PersonsTabType.PROPERTIES) {
                    actions.navigateToTab(PersonsTabType.PROPERTIES)
                }

                if (rawPersonDistinctId) {
                    // Decode the personDistinctId because it's coming from the URL, and it could be an email which gets encoded
                    const decodedPersonDistinctId = decodeURIComponent(rawPersonDistinctId)

                    if (!values.person || !values.person.distinct_ids.includes(decodedPersonDistinctId)) {
                        actions.loadPerson(decodedPersonDistinctId) // underscore contains the wildcard
                    }
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
