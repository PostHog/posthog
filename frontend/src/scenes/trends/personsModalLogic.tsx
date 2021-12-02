import React from 'react'
import { Link } from 'lib/components/Link'
import { kea } from 'kea'
import { router } from 'kea-router'
import api, { PaginatedResponse } from 'lib/api'
import { errorToast, isGroupType, pluralize, toParams } from 'lib/utils'
import {
    ActionFilter,
    FilterType,
    InsightType,
    FunnelVizType,
    PropertyFilter,
    FunnelCorrelationResultsType,
    ActorType,
} from '~/types'
import { personsModalLogicType } from './personsModalLogicType'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { TrendActors } from 'scenes/trends/types'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { filterTrendsClientSideParams } from 'scenes/insights/sharedUtils'
import { ACTIONS_LINE_GRAPH_CUMULATIVE } from 'lib/constants'
import { toast } from 'react-toastify'
import { cohortsModel } from '~/models/cohortsModel'
import { dayjs } from 'lib/dayjs'
import { groupsModel } from '~/models/groupsModel'

export interface PersonsModalParams {
    action: ActionFilter | 'session' // todo, refactor this session string param out
    label: string // Contains the step name
    date_from: string | number
    date_to: string | number
    filters: Partial<FilterType>
    breakdown_value?: string | number
    saveOriginal?: boolean
    searchTerm?: string
    funnelStep?: number
    pathsDropoff?: boolean
    pointValue?: number // The y-axis value of the data point (i.e. count, unique persons, ...)
}

export interface PeopleParamType {
    action: ActionFilter | 'session'
    label: string
    date_to?: string | number
    date_from?: string | number
    breakdown_value?: string | number
    target_date?: number | string
    lifecycle_type?: string | number
}

export function parsePeopleParams(peopleParams: PeopleParamType, filters: Partial<FilterType>): string {
    const { action, date_from, date_to, breakdown_value, ...restParams } = peopleParams
    const params = filterTrendsClientSideParams({
        ...filters,
        entity_id: (action !== 'session' && action.id) || filters?.events?.[0]?.id || filters?.actions?.[0]?.id,
        entity_type: (action !== 'session' && action.type) || filters?.events?.[0]?.type || filters?.actions?.[0]?.type,
        entity_math: (action !== 'session' && action.math) || undefined,
        breakdown_value,
    })

    // casting here is not the best
    if (filters.insight === InsightType.STICKINESS) {
        params.stickiness_days = date_from as number
    } else if (params.display === ACTIONS_LINE_GRAPH_CUMULATIVE) {
        params.date_to = date_from as string
    } else if (filters.insight === InsightType.LIFECYCLE) {
        params.date_from = filters.date_from
        params.date_to = filters.date_to
    } else {
        params.date_from = date_from as string
        params.date_to = date_to as string
    }

    // If breakdown type is cohort, we use breakdown_value
    // If breakdown type is event, we just set another filter
    if (breakdown_value && filters.breakdown_type != 'cohort' && filters.breakdown_type != 'person') {
        params.properties = [
            ...(params.properties || []),
            { key: params.breakdown, value: breakdown_value, type: 'event' } as PropertyFilter,
        ]
    }
    if (action !== 'session' && action.properties) {
        params.properties = [...(params.properties || []), ...action.properties]
    }

    return toParams({ ...params, ...restParams })
}

// Props for the `loadPeopleFromUrl` action.
// NOTE: this interface isn't particularly clean. Separation of concerns of load
// and displaying of people and the display of the modal would be helpful to
// keep this interfaces smaller.
type LoadPeopleFromUrlProps = {
    // The url from which we can load urls
    url: string
    // The funnel step the dialog should display as the complete/dropped step.
    // Optional as this call signature includes any parameter from any insght type
    funnelStep?: number
    // Used to display in the modal title the property value we're filtering
    // with
    breakdown_value?: string | number // NOTE: using snake case to be consistent with the rest of the file
    // This label is used in the modal title. It's usage depends on the
    // filter.insight attribute. For insight=FUNNEL we use it as a person
    // property name
    label: string
    // Needed for display
    date_from?: string | number
    // Copied from `PersonsModalParams`, likely needed for display logic
    action: ActionFilter | 'session'
    // Copied from `PersonsModalParams`, likely needed for diplay logic
    pathsDropoff?: boolean
}

export const personsModalLogic = kea<personsModalLogicType<LoadPeopleFromUrlProps, PersonsModalParams>>({
    path: ['scenes', 'trends', 'personsModalLogic'],
    actions: () => ({
        setSearchTerm: (term: string) => ({ term }),
        setCohortModalVisible: (visible: boolean) => ({ visible }),
        loadPeople: (peopleParams: PersonsModalParams) => ({ peopleParams }),
        loadPeopleFromUrl: (props: LoadPeopleFromUrlProps) => props,
        loadMorePeople: true,
        hidePeople: true,
        saveCohortWithFilters: (cohortName: string, filters: Partial<FilterType>) => ({ cohortName, filters }),
        setPersonsModalFilters: (searchTerm: string, people: TrendActors, filters: Partial<FilterType>) => ({
            searchTerm,
            people,
            filters,
        }),
        saveFirstLoadedActors: (people: TrendActors) => ({ people }),
        setFirstLoadedActors: (firstLoadedPeople: TrendActors | null) => ({ firstLoadedPeople }),
    }),
    connect: {
        values: [groupsModel, ['groupTypes']],
    },
    reducers: () => ({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { term }) => term,
                hidePeople: () => '',
            },
        ],
        cohortModalVisible: [
            false,
            {
                setCohortModalVisible: (_, { visible }) => visible,
            },
        ],
        people: [
            null as TrendActors | null,
            {
                loadPeople: (_, { peopleParams: { action, label, date_from, breakdown_value } }) => ({
                    people: [],
                    count: 0,
                    action,
                    label,
                    day: date_from,
                    breakdown_value,
                }),
                loadPeopleFromUrl: (_, { label, date_from = '', action, breakdown_value }) => ({
                    people: [],
                    count: 0,
                    day: date_from,
                    label,
                    action,
                    breakdown_value,
                }),
                setFilters: () => null,
                setFirstLoadedActors: (_, { firstLoadedPeople }) => firstLoadedPeople,
            },
        ],
        firstLoadedPeople: [
            null as TrendActors | null,
            {
                saveFirstLoadedActors: (_, { people }) => people,
            },
        ],
        loadingMorePeople: [
            false,
            {
                loadMorePeople: () => true,
                loadMorePeopleSuccess: () => false,
                loadMorePeopleFailure: () => false,
            },
        ],
        showingPeople: [
            false,
            {
                loadPeople: () => true,
                loadPeopleFromUrl: () => true,
                hidePeople: () => false,
            },
        ],
        peopleParams: [
            null as PersonsModalParams | null,
            {
                loadPeople: (_, { peopleParams }) => peopleParams,
            },
        ],
    }),
    selectors: {
        isInitialLoad: [
            (s) => [s.peopleLoading, s.loadingMorePeople],
            (peopleLoading, loadingMorePeople) => peopleLoading && !loadingMorePeople,
        ],
        clickhouseFeaturesEnabled: [
            () => [preflightLogic.selectors.preflight],
            (preflight) => !!preflight?.is_clickhouse_enabled,
        ],
        isGroupType: [(s) => [s.people], (people) => people?.people?.[0] && isGroupType(people.people[0])],
        actorLabel: [
            (s) => [s.people, s.isGroupType, s.groupTypes],
            (result, _isGroupType, groupTypes) => {
                if (_isGroupType && result?.action !== 'session') {
                    return result?.action.math_group_type_index != undefined &&
                        groupTypes.length > result?.action.math_group_type_index
                        ? `${groupTypes[result?.action.math_group_type_index].group_type}(s)`
                        : ''
                } else {
                    return pluralize(result?.count || 0, 'user', undefined, false)
                }
            },
        ],
    },
    loaders: ({ actions, values }) => ({
        people: {
            loadPeople: async ({ peopleParams }, breakpoint) => {
                let actors: PaginatedResponse<{
                    people: ActorType[]
                    count: number
                }> | null = null
                const {
                    label,
                    action,
                    filters,
                    date_from,
                    date_to,
                    breakdown_value,
                    saveOriginal,
                    searchTerm,
                    funnelStep,
                    pathsDropoff,
                } = peopleParams

                const searchTermParam = searchTerm ? `&search=${encodeURIComponent(searchTerm)}` : ''

                if (filters.funnel_correlation_person_entity) {
                    const cleanedParams = cleanFilters(filters)
                    actors = await api.create(`api/person/funnel/correlation/?${searchTermParam}`, cleanedParams)
                } else if (filters.insight === InsightType.LIFECYCLE) {
                    const filterParams = parsePeopleParams(
                        { label, action, target_date: date_from, lifecycle_type: breakdown_value },
                        filters
                    )
                    actors = await api.get(`api/person/lifecycle/?${filterParams}${searchTermParam}`)
                } else if (filters.insight === InsightType.STICKINESS) {
                    const filterParams = parsePeopleParams(
                        { label, action, date_from, date_to, breakdown_value },
                        filters
                    )
                    actors = await api.get(`api/person/stickiness/?${filterParams}${searchTermParam}`)
                } else if (funnelStep || filters.funnel_viz_type === FunnelVizType.Trends) {
                    let params
                    if (filters.funnel_viz_type === FunnelVizType.Trends) {
                        // funnel trends
                        const entrance_period_start = dayjs(date_from).format('YYYY-MM-DD HH:mm:ss')
                        params = { ...filters, entrance_period_start, drop_off: false }
                    } else {
                        // regular funnel steps
                        params = {
                            ...filters,
                            funnel_step: funnelStep,
                            ...(breakdown_value !== undefined && { funnel_step_breakdown: breakdown_value }),
                        }

                        // getting property correlations from funnel
                        if (params.funnel_custom_steps) {
                            eventUsageLogic.actions.reportCorrelationInteraction(
                                FunnelCorrelationResultsType.Properties,
                                'person modal',
                                filters.funnel_correlation_person_entity
                            )
                        }
                    }
                    const cleanedParams = cleanFilters(params)
                    const funnelParams = toParams(cleanedParams)
                    actors = await api.create(`api/person/funnel/?${funnelParams}${searchTermParam}`)
                } else if (filters.insight === InsightType.PATHS) {
                    const cleanedParams = cleanFilters(filters)
                    actors = await api.create(`api/person/path/?${searchTermParam}`, cleanedParams)
                } else {
                    actors = await api.actions.getPeople(
                        { label, action, date_from, date_to, breakdown_value },
                        filters,
                        searchTerm
                    )
                }
                breakpoint()
                const peopleResult = {
                    people: actors?.results[0]?.people,
                    count: actors?.results[0]?.count || 0,
                    action,
                    label,
                    day: date_from,
                    breakdown_value,
                    next: actors?.next,
                    funnelStep,
                    pathsDropoff,
                } as TrendActors

                eventUsageLogic.actions.reportPersonsModalViewed(peopleParams, peopleResult.count, !!actors?.next)

                if (saveOriginal) {
                    actions.saveFirstLoadedActors(peopleResult)
                }

                return peopleResult
            },
            loadPeopleFromUrl: async ({
                url,
                funnelStep,
                breakdown_value = '',
                date_from = '',
                action,
                label,
                pathsDropoff,
            }) => {
                const people = await api.get(url)

                return {
                    people: people?.results[0]?.people,
                    count: people?.results[0]?.count || 0,
                    label,
                    funnelStep,
                    breakdown_value,
                    day: date_from,
                    action: action,
                    next: people?.next,
                    pathsDropoff,
                }
            },
            loadMorePeople: async ({}, breakpoint) => {
                if (values.people) {
                    const {
                        people: currPeople,
                        count,
                        action,
                        label,
                        day,
                        breakdown_value,
                        next,
                        funnelStep,
                    } = values.people
                    if (!next) {
                        throw new Error('URL of next page of persons is not known.')
                    }
                    const people = await api.get(next)
                    breakpoint()

                    return {
                        people: [...currPeople, ...people.results[0]?.people],
                        count: count + people.results[0]?.count,
                        action,
                        label,
                        day,
                        breakdown_value,
                        next: people.next,
                        funnelStep,
                    }
                }
                return null
            },
        },
    }),
    listeners: ({ actions, values }) => ({
        saveCohortWithFilters: async ({ cohortName, filters }) => {
            if (values.people) {
                const { label, action, day, breakdown_value } = values.people
                const filterParams = parsePeopleParams(
                    { label, action, date_from: day, date_to: day, breakdown_value },
                    filters
                )
                const cohortParams = {
                    is_static: true,
                    name: cohortName,
                }
                const cohort = await api.create('api/cohort' + (filterParams ? '?' + filterParams : ''), cohortParams)
                cohortsModel.actions.cohortCreated(cohort)
                toast.success(
                    <div data-attr="success-toast">
                        <h1>Cohort saved successfully!</h1>
                        <p>
                            <Link to={'/cohorts/' + cohort.id}>Click here to see the cohort.</Link>
                        </p>
                    </div>,
                    {
                        toastId: `cohort-saved-${cohort.id}`,
                    }
                )
            } else {
                errorToast(undefined, "We couldn't create your cohort:")
            }
        },
        setPersonsModalFilters: async ({ searchTerm, people, filters }) => {
            const { label, action, day, breakdown_value, funnelStep } = people
            const date_from = day
            const date_to = day
            const saveOriginal = false
            actions.loadPeople({
                action,
                label,
                date_from,
                date_to,
                filters,
                breakdown_value,
                saveOriginal,
                searchTerm,
                funnelStep,
            })
        },
    }),
    actionToUrl: ({ values }) => ({
        loadPeople: () => {
            return [
                router.values.location.pathname,
                router.values.searchParams,
                { ...router.values.hashParams, personModal: values.peopleParams },
            ]
        },
        hidePeople: () => {
            // eslint-disable-next-line @typescript-eslint/no-unused-vars
            const { personModal: _discard, ...otherHashParams } = router.values.hashParams
            return [router.values.location.pathname, router.values.searchParams, otherHashParams]
        },
    }),
    urlToAction: ({ actions, values }) => ({
        '/insights/': (_, {}, { personModal }) => {
            if (personModal && !values.showingPeople) {
                actions.loadPeople(personModal)
            }
            if (!personModal && values.showingPeople) {
                actions.hidePeople()
            }
        },
    }),
})
