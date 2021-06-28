import { kea } from 'kea'
import api from 'lib/api'
import { ViewType } from 'scenes/insights/insightLogic'
import { ActionFilter, PersonType } from '~/types'
import { personsModalLogicType } from './personsModalLogicType'
import { parsePeopleParams, trendsLogic } from './trendsLogic'

interface TrendPeople {
    people: PersonType[]
    breakdown_value?: string
    count: number
    day: string | number
    next?: string
    label: string
    action: ActionFilter | string
    loadingMore?: boolean
}

export const personsModalLogic = kea<personsModalLogicType<TrendPeople>>({
    connect: {
        values: [trendsLogic({ dashboardItemId: null}), ['values']],
    },
    actions: () => ({
        loadPeople: (
            action: ActionFilter | string,
            label: string,
            date_from: string | number,
            date_to: string | number,
            breakdown_value?: string,
            saveOriginal?: boolean,
            searchTerm?: string
        ) => ({
            action,
            label,
            date_from,
            date_to,
            breakdown_value,
            saveOriginal,
            searchTerm,
        }),
        setLoadingMorePeople: (status: boolean) => ({ status }),
        setShowingPeople: (isShowing: boolean) => ({ isShowing }),
        setPeople: (
            people?: PersonType[],
            count?: number,
            action?: ActionFilter,
            label?: string,
            day?: string | number,
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
            action: ActionFilter,
            label: string,
            day: string | number,
            breakdown_value: string,
            next: string
        ) => ({
            people,
            count,
            action,
            label,
            day,
            breakdown_value,
            next,
        }),
    }),
    reducers: () => ({
        people: [
            null as TrendPeople | null,
            {
                setFilters: () => null,
                setPeople: (_, people: TrendPeople) => people,
            },
        ],
        firstLoadedPeople: [
            null as TrendPeople | null,
            {
                saveFirstLoadedPeople: (_, people: TrendPeople) => people,
            },
        ],
        loadingMorePeople: [
            false,
            {
                setLoadingMorePeople: (_, { status }: { status: boolean }) => status,
            },
        ],
        showingPeople: [
            false,
            {
                loadPeople: () => true,
                setShowingPeople: ({}, { isShowing }: { isShowing: boolean }) => isShowing,
            },
        ],
    }),
    selectors: () => ({
        // filters: [
        //     () => [trendsLogic?.values?.filters],
        //     (filters) => filters,
        // ]
    }),
    listeners: ({ actions, values }) => ({
        loadPeople: async (
            { label, action, date_from, date_to, breakdown_value, saveOriginal, searchTerm },
            breakpoint
        ) => {
            let people = []
            const searchTermParam = searchTerm ? `&search=${searchTerm}` : ''
            const filters = trendsLogic.values?.filters
            debugger
            // const filters = values.filters
            // const filters = {insight: ''}
            const insightType = filters?.insight
            if (insightType === ViewType.LIFECYCLE) {
                const filterParams = parsePeopleParams(
                    { label, action, target_date: date_from, lifecycle_type: breakdown_value },
                    filters
                )
                // actions.setPeople(null, null, action, label, date_from, breakdown_value, null)
                people = await api.get(`api/person/lifecycle/?${filterParams}${searchTermParam}`)
            } else if (insightType === ViewType.STICKINESS) {
                const filterParams = parsePeopleParams(
                    { label, action, date_from, date_to, breakdown_value },
                    filters
                )
                // actions.setPeople(null, null, action, label, date_from, breakdown_value, null)
                people = await api.get(`api/person/stickiness/?${filterParams}${searchTermParam}`)
            } else {
                const filterParams = parsePeopleParams(
                    { label, action, date_from, date_to, breakdown_value },
                    filters
                )
                // actions.setPeople(null, null, action, label, date_from, breakdown_value, null)
                people = await api.get(`api/action/people/?${filterParams}${searchTermParam}`)
            }
            breakpoint()
            actions.setPeople(
                people.results[0]?.people,
                people.results[0]?.count,
                action,
                label,
                date_from,
                breakdown_value,
                people.next
            )
            if (saveOriginal) {
                actions.saveFirstLoadedPeople(
                    people.results[0]?.people,
                    people.results[0]?.count,
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
    })
})
