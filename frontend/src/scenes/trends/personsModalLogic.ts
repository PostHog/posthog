import { kea } from 'kea'
import api from 'lib/api'
import { errorToast, toParams } from 'lib/utils'
import { cleanFunnelParams, funnelLogic } from 'scenes/funnels/funnelLogic'
import { ViewType } from 'scenes/insights/insightLogic'
import { cohortLogic } from 'scenes/persons/cohortLogic'
import { ActionFilter, FilterType } from '~/types'
import { personsModalLogicType } from './personsModalLogicType'
import { parsePeopleParams, TrendPeople } from './trendsLogic'

interface PersonModalParams {
    action: ActionFilter | 'session' // todo, refactor this session string param out
    label: string
    date_from: string | number
    date_to: string | number
    filters: Partial<FilterType>
    breakdown_value?: string
    saveOriginal?: boolean
    searchTerm?: string
    funnelStep?: number
}

export const personsModalLogic = kea<personsModalLogicType<PersonModalParams>>({
    actions: () => ({
        setSearchTerm: (term: string) => ({ term }),
        setCohortModalVisible: (visible: boolean) => ({ visible }),
        loadPeople: (peopleParams: PersonModalParams) => ({ peopleParams }),
        saveCohortWithFilters: (cohortName: string, filters: Partial<FilterType>) => ({ cohortName, filters }),
        loadMorePeople: true,
        setLoadingMorePeople: (status: boolean) => ({ status }),
        setShowingPeople: (isShowing: boolean) => ({ isShowing }),
        setPeople: (people: TrendPeople) => ({ people }),
        setPersonsModalFilters: (searchTerm: string, people: TrendPeople, filters: Partial<FilterType>) => ({
            searchTerm,
            people,
            filters,
        }),
        saveFirstLoadedPeople: (people: TrendPeople) => ({ people }),
        setFirstLoadedPeople: (firstLoadedPeople: TrendPeople | null) => ({ firstLoadedPeople }),
        refreshCohort: true,
        setPeopleLoading: (loading: boolean) => ({ loading }),
    }),
    reducers: () => ({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { term }) => term,
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
                setFilters: () => null,
                setPeople: (_, { people }) => people,
                setFirstLoadedPeople: (_, { firstLoadedPeople }) => firstLoadedPeople,
            },
        ],
        peopleLoading: [
            false,
            {
                setPeopleLoading: (_, { loading }) => loading,
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
                setLoadingMorePeople: (_, { status }) => status,
            },
        ],
        showingPeople: [
            false,
            {
                loadPeople: () => true,
                setShowingPeople: ({}, { isShowing }) => isShowing,
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        refreshCohort: () => {
            cohortLogic({
                cohort: {
                    id: 'new',
                    groups: [],
                },
            }).actions.setCohort({
                id: 'new',
                groups: [],
            })
        },
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
        loadPeople: async ({ peopleParams }, breakpoint) => {
            let people = []
            const {
                label,
                action,
                date_from,
                date_to,
                filters,
                breakdown_value,
                saveOriginal,
                searchTerm,
                funnelStep,
            } = peopleParams
            const searchTermParam = searchTerm ? `&search=${encodeURIComponent(searchTerm)}` : ''
            const tempPeople = { people: [], count: 0, action, label, day: date_from, breakdown_value }
            if (filters.insight === ViewType.LIFECYCLE) {
                const filterParams = parsePeopleParams(
                    { label, action, target_date: date_from, lifecycle_type: breakdown_value },
                    filters
                )
                actions.setPeople(tempPeople)
                people = await api.get(`api/person/lifecycle/?${filterParams}${searchTermParam}`)
            } else if (filters.insight === ViewType.STICKINESS) {
                const filterParams = parsePeopleParams({ label, action, date_from, date_to, breakdown_value }, filters)
                actions.setPeople(tempPeople)
                people = await api.get(`api/person/stickiness/?${filterParams}${searchTermParam}`)
            } else if (funnelStep) {
                const params = { ...funnelLogic().values.filters, funnel_step: funnelStep }
                const cleanedParams = cleanFunnelParams(params)
                const funnelParams = toParams(cleanedParams)
                people = await api.create(`api/person/funnel/?${funnelParams}${searchTermParam}`)
            } else {
                const filterParams = parsePeopleParams({ label, action, date_from, date_to, breakdown_value }, filters)
                actions.setPeople(tempPeople)
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
            } as TrendPeople
            actions.setPeople(peopleResult)
            if (saveOriginal) {
                actions.saveFirstLoadedPeople(peopleResult)
            }
        },
        loadMorePeople: async ({}, breakpoint) => {
            if (values.people) {
                const { people: currPeople, count, action, label, day, breakdown_value, next } = values.people
                actions.setLoadingMorePeople(true)
                const people = await api.get(next)
                actions.setLoadingMorePeople(false)
                breakpoint()
                const morePeopleResult = {
                    people: [...currPeople, ...people.results[0]?.people],
                    count: count + people.results[0]?.count,
                    action,
                    label,
                    day,
                    breakdown_value,
                    next: people.next,
                }
                actions.setPeople(morePeopleResult)
            }
        },
        setPersonsModalFilters: async ({ searchTerm, people, filters }) => {
            const { label, action, day, breakdown_value } = people
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
            })
        },
    }),
})
