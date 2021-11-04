import React from 'react'
import { Link } from 'lib/components/Link'
import dayjs from 'dayjs'
import { kea } from 'kea'
import { router } from 'kea-router'
import api, { PaginatedResponse } from 'lib/api'
import { errorToast, toParams } from 'lib/utils'
import {
    ActionFilter,
    FilterType,
    ViewType,
    FunnelVizType,
    PropertyFilter,
    PersonType,
    FunnelCorrelationResultsType,
} from '~/types'
import { personsModalLogicType } from './personsModalLogicType'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { TrendPeople } from 'scenes/trends/types'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { filterTrendsClientSideParams } from 'scenes/insights/sharedUtils'
import { ACTIONS_LINE_GRAPH_CUMULATIVE } from 'lib/constants'
import { toast } from 'react-toastify'
import { cohortsModel } from '~/models/cohortsModel'

export interface PersonModalParams {
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
    if (filters.insight === ViewType.STICKINESS) {
        params.stickiness_days = date_from as number
    } else if (params.display === ACTIONS_LINE_GRAPH_CUMULATIVE) {
        params.date_to = date_from as string
    } else if (filters.insight === ViewType.LIFECYCLE) {
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

export const personsModalLogic = kea<personsModalLogicType<PersonModalParams>>({
    actions: () => ({
        setSearchTerm: (term: string) => ({ term }),
        setCohortModalVisible: (visible: boolean) => ({ visible }),
        loadPeople: (peopleParams: PersonModalParams) => ({ peopleParams }),
        loadMorePeople: true,
        hidePeople: true,
        saveCohortWithFilters: (cohortName: string, filters: Partial<FilterType>) => ({ cohortName, filters }),
        setPersonsModalFilters: (searchTerm: string, people: TrendPeople, filters: Partial<FilterType>) => ({
            searchTerm,
            people,
            filters,
        }),
        saveFirstLoadedPeople: (people: TrendPeople) => ({ people }),
        setFirstLoadedPeople: (firstLoadedPeople: TrendPeople | null) => ({ firstLoadedPeople }),
        savePeopleParams: (peopleParams: PersonModalParams) => ({ peopleParams }),
    }),
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
            null as TrendPeople | null,
            {
                loadPeople: (_, { peopleParams: { action, label, date_from, breakdown_value } }) => ({
                    people: [],
                    count: 0,
                    action,
                    label,
                    day: date_from,
                    breakdown_value,
                }),
                setFilters: () => null,
                setFirstLoadedPeople: (_, { firstLoadedPeople }) => firstLoadedPeople,
            },
        ],
        firstLoadedPeople: [
            null as TrendPeople | null,
            {
                saveFirstLoadedPeople: (_, { people }) => people,
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
                hidePeople: () => false,
            },
        ],
        peopleParams: [
            null as PersonModalParams | null,
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
    },
    loaders: ({ actions, values }) => ({
        people: {
            loadPeople: async ({ peopleParams }, breakpoint) => {
                let people: PaginatedResponse<{ people: PersonType[]; count: number }> | null = null
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
                    people = await api.create(`api/person/funnel/correlation/?${searchTermParam}`, cleanedParams)
                } else if (filters.insight === ViewType.LIFECYCLE) {
                    const filterParams = parsePeopleParams(
                        { label, action, target_date: date_from, lifecycle_type: breakdown_value },
                        filters
                    )
                    people = await api.get(`api/person/lifecycle/?${filterParams}${searchTermParam}`)
                } else if (filters.insight === ViewType.STICKINESS) {
                    const filterParams = parsePeopleParams(
                        { label, action, date_from, date_to, breakdown_value },
                        filters
                    )
                    people = await api.get(`api/person/stickiness/?${filterParams}${searchTermParam}`)
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
                    people = await api.create(`api/person/funnel/?${funnelParams}${searchTermParam}`)
                } else if (filters.insight === ViewType.PATHS) {
                    const cleanedParams = cleanFilters(filters)
                    people = await api.create(`api/person/path/?${searchTermParam}`, cleanedParams)
                } else {
                    people = await api.actions.getPeople(
                        { label, action, date_from, date_to, breakdown_value },
                        filters,
                        searchTerm
                    )
                }
                breakpoint()
                const peopleResult = {
                    people: people?.results[0]?.people,
                    count: people?.results[0]?.count || 0,
                    action,
                    label,
                    day: date_from,
                    breakdown_value,
                    next: people?.next,
                    funnelStep,
                    pathsDropoff,
                } as TrendPeople

                eventUsageLogic.actions.reportPersonModalViewed(peopleParams, peopleResult.count, !!people?.next)

                if (saveOriginal) {
                    actions.saveFirstLoadedPeople(peopleResult)
                }

                return peopleResult
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
        '/insights': (_, {}, { personModal }) => {
            if (personModal && !values.showingPeople) {
                actions.loadPeople(personModal)
            }
            if (!personModal && values.showingPeople) {
                actions.hidePeople()
            }
        },
    }),
})
