import { kea } from 'kea'
import api from 'lib/api'
import { errorToast, toParams } from 'lib/utils'
import { cleanFunnelParams, funnelLogic } from 'scenes/funnels/funnelLogic'
import { ViewType } from 'scenes/insights/insightLogic'
import { cohortLogic } from 'scenes/persons/cohortLogic'
import { ActionFilter, PersonType } from '~/types'
import { personsModalLogicType } from './personsModalLogicType'
import { parsePeopleParams, TrendPeople, trendsLogic } from './trendsLogic'

export const personsModalLogic = kea<personsModalLogicType>({
    connect: {
        values: [trendsLogic, ['filters']],
    },
    actions: () => ({
        setSearchTerm: (term: string) => ({ term }),
        setCohortModalVisible: (visible: boolean) => ({ visible }),
        loadPeople: (
            action: ActionFilter | 'session', // todo, refactor this session string param out
            label: string,
            date_from: string | number,
            date_to: string | number,
            breakdown_value?: string,
            saveOriginal?: boolean,
            searchTerm?: string,
            funnelStep?: number
        ) => ({
            action,
            label,
            date_from,
            date_to,
            breakdown_value,
            saveOriginal,
            searchTerm,
            funnelStep,
        }),
        saveCohortWithFilters: (cohortName: string) => ({ cohortName }),
        loadMorePeople: true,
        setLoadingMorePeople: (status: boolean) => ({ status }),
        setShowingPeople: (isShowing: boolean) => ({ isShowing }),
        setPeople: (
            people: PersonType[],
            count: number,
            action: ActionFilter | 'session',
            label: string,
            day: string | number,
            breakdown_value?: string,
            next?: string
        ) => ({
            people,
            count,
            action,
            label,
            day,
            breakdown_value,
            next,
        }),
        setPersonsModalFilters: (searchTerm: string, people: TrendPeople) => ({ searchTerm, people }),
        saveFirstLoadedPeople: (
            people: PersonType[],
            count: number,
            action: ActionFilter | 'session',
            label: string,
            day: string | number,
            breakdown_value?: string,
            next?: string
        ) => ({
            people,
            count,
            action,
            label,
            day,
            breakdown_value,
            next,
        }),
        setFirstLoadedPeople: (firstLoadedPeople: TrendPeople | null) => ({ firstLoadedPeople }),
        refreshCohort: true,
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
                setPeople: (_, people) => people,
                setFirstLoadedPeople: (_, { firstLoadedPeople }) => firstLoadedPeople,
            },
        ],
        firstLoadedPeople: [
            null as TrendPeople | null,
            {
                saveFirstLoadedPeople: (_, people) => people,
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
        saveCohortWithFilters: ({ cohortName }) => {
            if (values.people) {
                const { label, action, day, breakdown_value } = values.people
                const filterParams = parsePeopleParams(
                    { label, action, date_from: day, date_to: day, breakdown_value },
                    trendsLogic().values.filters
                )
                const cohortParams = {
                    is_static: true,
                    name: cohortName,
                }
                cohortLogic({
                    cohort: {
                        id: 'new',
                        groups: [],
                    },
                }).actions.saveCohort(cohortParams, filterParams)
            } else {
                errorToast(undefined, "We couldn't create your cohort:")
            }
        },
        loadPeople: async (
            { label, action, date_from, date_to, breakdown_value, saveOriginal, searchTerm, funnelStep },
            breakpoint
        ) => {
            let people = []
            const searchTermParam = searchTerm ? `&search=${encodeURIComponent(searchTerm)}` : ''
            if (trendsLogic().values.filters.insight === ViewType.LIFECYCLE) {
                const filterParams = parsePeopleParams(
                    { label, action, target_date: date_from, lifecycle_type: breakdown_value },
                    trendsLogic().values.filters
                )
                actions.setPeople([], 0, action, label, date_from, breakdown_value, '')
                people = await api.get(`api/person/lifecycle/?${filterParams}${searchTermParam}`)
            } else if (trendsLogic().values.filters.insight === ViewType.STICKINESS) {
                const filterParams = parsePeopleParams(
                    { label, action, date_from, date_to, breakdown_value },
                    trendsLogic().values.filters
                )
                actions.setPeople([], 0, action, label, date_from, breakdown_value, '')
                people = await api.get(`api/person/stickiness/?${filterParams}${searchTermParam}`)
            } else if (funnelStep) {
                const params = { ...funnelLogic().values.filters, funnel_step: funnelStep }
                const cleanedParams = cleanFunnelParams(params)
                const funnelParams = toParams(cleanedParams)
                people = await api.create(`api/person/funnel/?${funnelParams}${searchTermParam}`)
            } else {
                const filterParams = parsePeopleParams(
                    { label, action, date_from, date_to, breakdown_value },
                    trendsLogic().values.filters
                )
                actions.setPeople([], 0, action, label, date_from, breakdown_value, '')
                people = await api.get(`api/action/people/?${filterParams}${searchTermParam}`)
            }
            breakpoint()
            actions.setPeople(
                people.results[0]?.people,
                people.results[0]?.count || 0,
                action,
                label,
                date_from,
                breakdown_value,
                people.next
            )
            if (saveOriginal) {
                actions.saveFirstLoadedPeople(
                    people.results[0]?.people,
                    people.results[0]?.count || 0,
                    action,
                    label,
                    date_from,
                    breakdown_value,
                    people.next
                )
            }
        },
        loadMorePeople: async ({}, breakpoint) => {
            if (values.people) {
                const { people: currPeople, count, action, label, day, breakdown_value, next } = values.people
                actions.setLoadingMorePeople(true)
                const people = await api.get(next)
                actions.setLoadingMorePeople(false)
                breakpoint()
                actions.setPeople(
                    [...currPeople, ...people.results[0]?.people],
                    count + people.results[0]?.count,
                    action,
                    label,
                    day,
                    breakdown_value,
                    people.next
                )
            }
        },
        setPersonsModalFilters: async ({ searchTerm, people }) => {
            const { label, action, day, breakdown_value } = people
            const date_from = day
            const date_to = day
            actions.loadPeople(action, label, date_from, date_to, breakdown_value, false, searchTerm)
        },
    }),
})
