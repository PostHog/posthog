import { kea } from 'kea'
import api from 'lib/api'
import { errorToast, toParams } from 'lib/utils'
import { cleanFunnelParams, funnelLogic } from 'scenes/funnels/funnelLogic'
import { cohortLogic } from 'scenes/persons/cohortLogic'
import { ActionFilter, FilterType, PersonType, SessionType, ViewType } from '~/types'
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

function matchSessionsWithPeople(people: PersonType[], sessions: SessionType[]): PersonType[] {
    const mockPeople = [
        {
            id: 1988,
            name: 'jayne.joseph@hotmail.com',
            distinct_ids: ['017ac14e-9275-0000-f8db-4acfaf3faaa9'],
            properties: {
                name: {
                    last: 'Joseph',
                    first: 'Jayne',
                },
                email: 'jayne.joseph@hotmail.com',
                phone: '+1 (849) 532-2569',
                address: '463 Fayette Street, Gardiner, Rhode Island, 6302',
                is_demo: true,
            },
            is_identified: true,
            created_at: '2021-07-20T00:26:29.948169Z',
            uuid: '017ac14e-9231-0001-d8c2-9921858c0b1e',
        },
        {
            id: 1987,
            name: 'hubbard.powell@gmail.com',
            distinct_ids: ['017ac14e-9274-0007-d507-5c7a438ac6b6'],
            properties: {
                name: {
                    last: 'Powell',
                    first: 'Hubbard',
                },
                email: 'hubbard.powell@gmail.com',
                phone: '+1 (916) 465-3645',
                address: '250 Falmouth Street, Jardine, Nevada, 2810',
                is_demo: true,
            },
            is_identified: true,
            created_at: '2021-07-20T00:26:29.948095Z',
            uuid: '017ac14e-9231-0000-55db-c8e5e6c23f31',
        },
        {
            id: 1984,
            name: 'smith.nunez@gmail.com',
            distinct_ids: ['017ac14e-9274-0004-eac9-6ef7892fc19a'],
            properties: {
                name: {
                    last: 'Nunez',
                    first: 'Smith',
                },
                email: 'smith.nunez@gmail.com',
                phone: '+1 (807) 451-2087',
                address: '670 Stryker Street, Gloucester, Minnesota, 2058',
                is_demo: true,
            },
            is_identified: true,
            created_at: '2021-07-20T00:26:29.947836Z',
            uuid: '017ac14e-9230-0000-74c4-034f2a978626',
        },
    ]
    const mockSessions = [
        {
            distinct_id: 'jXxaWiOntMbCdOuRVJIxTNJ4a3k2TpzmkjnOUrMRLuS',
            global_session_id: 41,
            length: 175,
            start_time: '2021-07-19T23:56:29.821000Z',
            end_time: '2021-07-19T23:59:24.005000Z',
            start_url: null,
            end_url: 'https://teq-posthog-dev.herokuapp.com/events?properties=%7B%7D',
            matching_events: [],
            email: 'zeke+dev@tequitable.com',
            session_recordings: [],
        },
        {
            distinct_id: 'Orbit Love Report Sync',
            global_session_id: 24,
            length: 86339,
            start_time: '2021-07-19T00:00:14.248000Z',
            end_time: '2021-07-19T23:59:13.690000Z',
            start_url: null,
            end_url: null,
            matching_events: [],
            email: 'smith.nunez@gmail.com',
            session_recordings: [
                {
                    id: '17ac1325a6e3c-04fadeb1b4be558-4c3f2d73-15f900-17ac1325a6f4ee',
                    recording_duration: 165,
                    viewed: false,
                },
            ],
        },
        {
            distinct_id: '843738a51abceeb8b997d4f5b7b8ec0d',
            global_session_id: 13,
            length: 86340,
            start_time: '2021-07-19T00:00:00.809000Z',
            end_time: '2021-07-19T23:59:00.576000Z',
            start_url: null,
            end_url: null,
            matching_events: [],
            email: null,
            session_recordings: [],
        },
    ]
    const fakeResponse = mockPeople.map((p) => {
        const sessionRecording = mockSessions.find(
            (s) =>
                s.email === p.properties.email &&
                s.session_recordings.length > 0 &&
                s.session_recordings[0].recording_duration > 0
        )
        p.session_recording = sessionRecording?.session_recordings[0].id
        return p
    })
    return people.map((p) => {
        const sessionRecording = sessions.find(
            (s) =>
                s.email === p.properties.email &&
                s.session_recordings.length > 0 &&
                s.session_recordings[0].recording_duration > 0
        )
        p.session_recording = sessionRecording?.session_recordings[0].id
        return p
    })
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
                    id: 'personsModalNew',
                    groups: [],
                },
            }).actions.setCohort({
                id: 'personsModalNew',
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
            actions.setPeopleLoading(true)
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
            actions.setPeopleLoading(false)
            const peopleResult = {
                people: matchSessionsWithPeople(people.results[0]?.people, people.results[0]?.sessions),
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
