import dayjs from 'dayjs'
import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { errorToast, toParams } from 'lib/utils'
import { cleanFunnelParams } from 'scenes/funnels/funnelLogic'
import { ActionFilter, FilterType, ViewType, FunnelVizType } from '~/types'
import { personsModalLogicType } from './personsModalLogicType'
import { parsePeopleParams } from './trendsLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { cohortLogic } from 'scenes/cohorts/cohortLogic'
import { TrendPeople } from 'scenes/trends/types'

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
                let people = []
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
                } = peopleParams
                const searchTermParam = searchTerm ? `&search=${encodeURIComponent(searchTerm)}` : ''

                if (filters.insight === ViewType.LIFECYCLE) {
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
                    }
                    const cleanedParams = cleanFunnelParams(params)
                    const funnelParams = toParams(cleanedParams)
                    people = await api.create(`api/person/funnel/?${funnelParams}${searchTermParam}`)
                } else {
                    const filterParams = parsePeopleParams(
                        { label, action, date_from, date_to, breakdown_value },
                        filters
                    )
                    people = await api.get(`api/action/people/?${filterParams}${searchTermParam}`)
                }
                breakpoint()
                const peopleResult = {
                    people: people.results[0]?.people,
                    count: people.results[0]?.count || 0,
                    action,
                    label,
                    day: date_from,
                    breakdown_value,
                    next: people.next,
                    funnelStep,
                } as TrendPeople

                eventUsageLogic.actions.reportPersonModalViewed(peopleParams, peopleResult.count, !!people.next)

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
        saveCohortWithFilters: ({ cohortName, filters }) => {
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
                cohortLogic({
                    cohort: {
                        id: 'personsModalNew',
                        groups: [],
                    },
                }).actions.saveCohort(cohortParams, filterParams)
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
