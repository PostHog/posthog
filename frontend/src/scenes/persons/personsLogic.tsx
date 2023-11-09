import { loaders } from 'kea-loaders'
import { kea, props, key, path, connect, actions, reducers, selectors, listeners, events } from 'kea'
import { decodeParams, router, actionToUrl, urlToAction } from 'kea-router'
import api, { CountedPaginatedResponse } from 'lib/api'
import type { personsLogicType } from './personsLogicType'
import {
    PersonPropertyFilter,
    Breadcrumb,
    CohortType,
    ExporterFormat,
    PersonListParams,
    PersonsTabType,
    PersonType,
    AnyPropertyFilter,
} from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'
import { teamLogic } from 'scenes/teamLogic'
import { convertPropertyGroupToProperties, toParams } from 'lib/utils'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { TriggerExportProps } from 'lib/components/ExportButton/exporter'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { asDisplay } from './person-utils'
import { hogqlQuery } from '~/queries/query'

export interface PersonsLogicProps {
    cohort?: number | 'new'
    syncWithUrl?: boolean
    urlId?: string
    fixedProperties?: PersonPropertyFilter[]
}

export const personsLogic = kea<personsLogicType>([
    props({} as PersonsLogicProps),
    key((props) => {
        if (props.fixedProperties) {
            return JSON.stringify(props.fixedProperties)
        }

        return props.cohort ? `cohort_${props.cohort}` : 'scene'
    }),
    path((key) => ['scenes', 'persons', 'personsLogic', key]),
    connect(() => ({
        actions: [eventUsageLogic, ['reportPersonDetailViewed']],
        values: [teamLogic, ['currentTeam'], featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setPerson: (person: PersonType | null) => ({ person }),
        setPersons: (persons: PersonType[]) => ({ persons }),
        loadPerson: (id: string) => ({ id }),
        loadPersonUUID: (uuid: string) => ({ uuid }),
        loadPersons: (url: string | null = '') => ({ url }),
        setListFilters: (payload: PersonListParams) => ({ payload }),
        setHiddenListProperties: (payload: AnyPropertyFilter[]) => ({ payload }),
        editProperty: (key: string, newValue?: string | number | boolean | null) => ({ key, newValue }),
        deleteProperty: (key: string) => ({ key }),
        navigateToCohort: (cohort: CohortType) => ({ cohort }),
        navigateToTab: (tab: PersonsTabType) => ({ tab }),
        setActiveTab: (tab: PersonsTabType) => ({ tab }),
        setSplitMergeModalShown: (shown: boolean) => ({ shown }),
        setDistinctId: (distinctId: string) => ({ distinctId }),
    }),
    loaders(({ values, actions, props }) => ({
        persons: [
            { next: null, previous: null, count: 0, results: [], offset: 0 } as CountedPaginatedResponse<PersonType> & {
                offset: number
            },
            {
                loadPersons: async ({ url }) => {
                    let result: CountedPaginatedResponse<PersonType> & { offset: number }
                    if (!url) {
                        const newFilters: PersonListParams = { ...values.listFilters }
                        newFilters.properties = [
                            ...(values.listFilters.properties || []),
                            ...values.hiddenListProperties,
                        ]
                        if (values.featureFlags[FEATURE_FLAGS.POSTHOG_3000]) {
                            newFilters.include_total = true // The total count is slow, but needed for infinite loading
                        }
                        if (props.cohort) {
                            result = {
                                ...(await api.get(`api/cohort/${props.cohort}/persons/?${toParams(newFilters)}`)),
                                offset: 0,
                            }
                        } else {
                            result = { ...(await api.persons.list(newFilters)), offset: 0 }
                        }
                    } else {
                        result = { ...(await api.get(url)), offset: parseInt(decodeParams(url).offset) }
                    }
                    return result
                },
            },
        ],
        person: [
            null as PersonType | null,
            {
                loadPerson: async ({ id }): Promise<PersonType | null> => {
                    if (values.featureFlags[FEATURE_FLAGS.PERSONS_HOGQL_QUERY]) {
                        const response = await hogqlQuery(
                            'select id, groupArray(pdi.distinct_id) as distinct_ids, properties, is_identified, created_at from persons where pdi.distinct_id={distinct_id} group by id, properties, is_identified, created_at',
                            { distinct_id: id }
                        )
                        const row = response?.results?.[0]
                        if (row) {
                            const person: PersonType = {
                                id: row[0],
                                uuid: row[0],
                                distinct_ids: row[1],
                                properties: JSON.parse(row[2] || '{}'),
                                is_identified: !!row[3],
                                created_at: row[4],
                            }
                            actions.reportPersonDetailViewed(person)
                            return person
                        }
                    }

                    const response = await api.persons.list({ distinct_id: id })
                    const person = response.results[0]
                    if (person) {
                        actions.reportPersonDetailViewed(person)
                    }
                    return person
                },
                loadPersonUUID: async ({ uuid }): Promise<PersonType | null> => {
                    const response = await hogqlQuery(
                        'select id, groupArray(pdi.distinct_id) as distinct_ids, properties, is_identified, created_at from persons where id={id} group by id, properties, is_identified, created_at',
                        { id: uuid }
                    )
                    const row = response?.results?.[0]
                    if (row) {
                        const person: PersonType = {
                            id: row[0],
                            uuid: row[0],
                            distinct_ids: row[1],
                            properties: JSON.parse(row[2] || '{}'),
                            is_identified: !!row[3],
                            created_at: row[4],
                        }
                        actions.reportPersonDetailViewed(person)
                        return person
                    }
                    return null
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
    })),
    reducers(() => ({
        listFilters: [
            {} as PersonListParams,
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
        hiddenListProperties: [
            [] as AnyPropertyFilter[],
            {
                setHiddenListProperties: (state, { payload }) => {
                    let newProperties = [...state, ...payload]
                    if (newProperties) {
                        newProperties =
                            convertPropertyGroupToProperties(newProperties.filter(isValidPropertyFilter)) || []
                    }
                    return newProperties
                },
            },
        ],
        activeTab: [
            null as PersonsTabType | null,
            {
                navigateToTab: (_, { tab }) => tab,
                setActiveTab: (_, { tab }) => tab,
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
            setPersons: (state, { persons }) => ({
                ...state,
                results: [...persons, ...state.results],
            }),
        },
        person: {
            loadPerson: () => null,
            setPerson: (_, { person }): PersonType | null => person,
        },
        distinctId: [
            null as string | null,
            {
                setDistinctId: (_, { distinctId }) => distinctId,
            },
        ],
    })),
    selectors(() => ({
        apiDocsURL: [
            () => [(_, props) => props.cohort],
            (cohort: PersonsLogicProps['cohort']) =>
                cohort
                    ? 'https://posthog.com/docs/api/cohorts#get-api-projects-project_id-cohorts-id-persons'
                    : 'https://posthog.com/docs/api/persons',
        ],
        cohortId: [() => [(_, props) => props.cohort], (cohort: PersonsLogicProps['cohort']) => cohort],
        currentTab: [(s) => [s.activeTab, s.defaultTab], (activeTab, defaultTab) => activeTab || defaultTab],
        defaultTab: [
            (s) => [s.feedEnabled],
            (feedEnabled) => (feedEnabled ? PersonsTabType.FEED : PersonsTabType.PROPERTIES),
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

        exporterProps: [
            (s) => [s.listFilters, (_, { cohort }) => cohort],
            (listFilters, cohort: number | 'new' | undefined): TriggerExportProps[] => [
                {
                    export_format: ExporterFormat.CSV,
                    export_context: {
                        path: cohort
                            ? api.cohorts.determineListUrl(cohort, listFilters)
                            : api.persons.determineListUrl(listFilters),
                    },
                },
            ],
        ],
        urlId: [() => [(_, props) => props.urlId], (urlId) => urlId],
        showCustomerSuccessDashboards: [
            (s) => [s.featureFlags],
            (featureFlags) => featureFlags[FEATURE_FLAGS.CS_DASHBOARDS],
        ],
        feedEnabled: [(s) => [s.featureFlags], (featureFlags) => !!featureFlags[FEATURE_FLAGS.PERSON_FEED_CANVAS]],
    })),
    listeners(({ actions, values }) => ({
        editProperty: async ({ key, newValue }) => {
            const person = values.person

            if (person && person.id) {
                let parsedValue = newValue

                // Instrumentation stuff
                let action: 'added' | 'updated'
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
                // :KLUDGE: Person properties are updated asynchronously in the plugin server - the response won't reflect
                //      the _updated_ properties yet.
                await api.persons.updateProperty(person.id, key, parsedValue)
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

            if (person && person.id) {
                const updatedProperties = { ...person.properties }
                delete updatedProperties[key]

                actions.setPerson({ ...person, properties: updatedProperties }) // To update the UI immediately
                // await api.create(`api/person/${person.id}/delete_property`, { $unset: key })
                await api.persons.deleteProperty(person.id, key)
                lemonToast.success(`Person property deleted`)

                eventUsageLogic.actions.reportPersonPropertyUpdated('removed', 1, undefined, undefined)
            }
        },
        navigateToCohort: ({ cohort }) => {
            router.actions.push(urls.cohort(cohort.id))
        },
    })),
    actionToUrl(({ values, props }) => ({
        setListFilters: () => {
            if (props.syncWithUrl && router.values.location.pathname.indexOf('/persons') > -1) {
                return ['/persons', values.listFilters, undefined, { replace: true }]
            }
        },
        navigateToTab: () => {
            if (props.syncWithUrl && router.values.location.pathname.indexOf('/person') > -1) {
                const searchParams = {}

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
    })),
    urlToAction(({ actions, values, props }) => ({
        '/person/*': ({ _: rawPersonDistinctId }, { sessionRecordingId }, { activeTab }) => {
            if (props.syncWithUrl) {
                if (sessionRecordingId && values.activeTab !== PersonsTabType.SESSION_RECORDINGS) {
                    actions.navigateToTab(PersonsTabType.SESSION_RECORDINGS)
                } else if (activeTab && values.activeTab !== activeTab) {
                    actions.navigateToTab(activeTab as PersonsTabType)
                }

                if (!activeTab) {
                    actions.setActiveTab(values.defaultTab)
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
        '/persons/*': ({ _: rawPersonUUID }, { sessionRecordingId }, { activeTab }) => {
            if (props.syncWithUrl) {
                if (sessionRecordingId && values.activeTab !== PersonsTabType.SESSION_RECORDINGS) {
                    actions.navigateToTab(PersonsTabType.SESSION_RECORDINGS)
                } else if (activeTab && values.activeTab !== activeTab) {
                    actions.navigateToTab(activeTab as PersonsTabType)
                }

                if (!activeTab) {
                    actions.setActiveTab(values.defaultTab)
                }

                if (rawPersonUUID) {
                    const decodedPersonUUID = decodeURIComponent(rawPersonUUID)
                    if (!values.person || values.person.id != decodedPersonUUID) {
                        actions.loadPersonUUID(decodedPersonUUID)
                    }
                }
            }
        },
    })),
    events(({ props, actions }) => ({
        afterMount: () => {
            if (props.cohort && typeof props.cohort === 'number') {
                actions.setListFilters({ cohort: props.cohort })
                actions.loadPersons()
            }

            if (props.fixedProperties) {
                actions.setHiddenListProperties(props.fixedProperties)
                actions.loadPersons()
            }
        },
    })),
])
