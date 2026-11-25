import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { type AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import {
    AiObservabilityPeopleListOrder,
    type PeopleFirstSeenRequestApi,
    type PersonListApi,
    type PersonListItemApi,
    type SessionListApi,
    type SessionPageRequestApi,
    type TraceListApi,
    type TracePageRequestApi,
} from '../../generated/api.schemas'
import { listFiltersLogic } from '../lists/listFiltersLogic'
import { SESSION_CELL_URLS, makeSessionListPage, makeSessionPreview } from '../sessions/testFixtures'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { TRACE_CELL_URLS, makeTraceListPage, makeTracePreview, ready } from '../traces/testFixtures'
import { PEOPLE_LIST_FILTERS, peopleListLogic } from './peopleListLogic'
import { personDrawerLogic } from './personDrawerLogic'
import {
    PEOPLE_FIRST_SEEN_URL,
    PEOPLE_NEW_COUNT_URL,
    PEOPLE_URL,
    PERSON_URL,
    makeFirstSeenAnswer,
    makePersonListItem,
    makePersonListPage,
} from './testFixtures'

const TRACES_URL = '/api/projects/:team_id/ai_observability/traces/'
const SESSIONS_URL = '/api/projects/:team_id/ai_observability/sessions/'
const LISTED = 'person-listed'
const UNLISTED = 'person-unlisted'
const RANGE = { date_from: '-24h', filter_test_accounts: 'false' }
const PAGE = makePersonListPage([LISTED])
const MODEL_FILTER: AnyPropertyFilter = {
    key: '$ai_model',
    value: ['gpt-test'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

type Answer<T> = [number, T | { detail: string }]

describe('personDrawerLogic', () => {
    let peopleReads: Record<string, string>[]
    let traceReads: Record<string, string>[]
    let sessionReads: Record<string, string>[]
    let tracePreviewBodies: TracePageRequestApi[]
    let sessionPreviewBodies: SessionPageRequestApi[]
    let firstSeenBodies: PeopleFirstSeenRequestApi[]
    let lookUpAnswer: Answer<PersonListItemApi>
    let lookUpHeld: Promise<void> | null
    let pageAnswer: PersonListApi
    let pageHeld: Promise<void> | null
    let tracesAnswer: () => Answer<TraceListApi>
    let sessionsAnswer: Answer<SessionListApi>
    let logic: ReturnType<typeof personDrawerLogic.build>

    function params(request: Request): Record<string, string> {
        return Object.fromEntries(new URL(request.url).searchParams)
    }

    function held(): [Promise<void>, () => void] {
        let release = (): void => {}
        const promise = new Promise<void>((resolve) => {
            release = resolve
        })
        return [promise, release]
    }

    async function openPerson(personId: string, listParams: Record<string, unknown> = {}): Promise<void> {
        router.actions.push(combineUrl(urls.aiObservabilityUsers(), { ...listParams, person: personId }).url)
        peopleListLogic.mount()
        await expectLogic(peopleListLogic).toFinishAllListeners()
        logic = personDrawerLogic({ personId })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        localStorage.clear()
        peopleReads = []
        traceReads = []
        sessionReads = []
        tracePreviewBodies = []
        sessionPreviewBodies = []
        firstSeenBodies = []
        lookUpAnswer = [200, makePersonListItem({ id: UNLISTED })]
        tracesAnswer = () => [200, makeTraceListPage(['trace-a', 'trace-b'])]
        sessionsAnswer = [200, makeSessionListPage(['session-a'])]
        lookUpHeld = null
        pageAnswer = PAGE
        pageHeld = null
        useMocks({
            get: {
                [PEOPLE_URL]: async ({ request }) => {
                    peopleReads.push(params(request))
                    await pageHeld
                    return [200, pageAnswer]
                },
                [PEOPLE_NEW_COUNT_URL]: { count: 0 },
                [PERSON_URL]: async ({ request, params: path }) => {
                    peopleReads.push({ ...params(request), person_id: String(path.person_id) })
                    await lookUpHeld
                    return lookUpAnswer
                },
                [TRACES_URL]: ({ request }) => {
                    traceReads.push(params(request))
                    return tracesAnswer()
                },
                [SESSIONS_URL]: ({ request }) => {
                    sessionReads.push(params(request))
                    return sessionsAnswer
                },
            },
            post: {
                [TRACE_CELL_URLS.previews]: async ({ request }: { request: Request }) => {
                    const body: TracePageRequestApi = await request.json()
                    tracePreviewBodies.push(body)
                    return [200, { items: body.trace_ids.map((id) => makeTracePreview(id)) }]
                },
                [SESSION_CELL_URLS.titles]: async ({ request }: { request: Request }) => {
                    const body: SessionPageRequestApi = await request.json()
                    sessionPreviewBodies.push(body)
                    return [200, { items: body.session_ids.map((id) => makeSessionPreview(id)) }]
                },
                [PEOPLE_FIRST_SEEN_URL]: async ({ request }: { request: Request }) => {
                    const body: PeopleFirstSeenRequestApi = await request.json()
                    firstSeenBodies.push(body)
                    return [200, makeFirstSeenAnswer(body.person_ids)]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic.unmount()
        peopleListLogic.unmount()
        jest.restoreAllMocks()
    })

    it("paints the header from the list's row without reading the person", async () => {
        await openPerson(LISTED)

        expect(logic.values).toMatchObject({ person: PAGE.results[0], status: 'ready' })
        expect(peopleReads.filter((read) => read.person_id)).toEqual([])
    })

    it.each([
        ['shows their row', true, 'ready'],
        ['says when the range does not hold them', false, 'not_found'],
    ])('reads a person the list does not hold, and %s', async (_name, holdsThem, status) => {
        if (!holdsThem) {
            lookUpAnswer = [404, { detail: 'Person not found in this range.' }]
        }

        await openPerson(UNLISTED)

        expect(peopleReads.filter((read) => read.person_id)).toEqual([{ ...RANGE, person_id: UNLISTED }])
        expect(logic.values.status).toEqual(status)
        expect(logic.values.person?.id ?? null).toEqual(holdsThem ? UNLISTED : null)
    })

    it('reads the first seen of a person the list does not hold, in the range', async () => {
        await openPerson(UNLISTED)

        expect(firstSeenBodies.at(-1)).toEqual({
            person_ids: [UNLISTED],
            date_from: '-24h',
            filter_test_accounts: false,
        })
        expect(logic.values.firstSeen).toEqual(
            ready({ firstSeen: '2026-11-02T10:00:00Z', checkedFrom: '2026-10-18', isNew: false })
        )
    })

    it("reads the person's five latest traces and sessions with their titles, and reads them again in a new range", async () => {
        await openPerson(LISTED)

        expect(traceReads).toEqual([{ ...RANGE, person_id: LISTED, limit: '5' }])
        expect(sessionReads).toEqual([{ ...RANGE, person_id: LISTED, limit: '5' }])
        expect(tracePreviewBodies).toEqual([{ trace_ids: ['trace-a', 'trace-b'] }])
        expect(sessionPreviewBodies).toEqual([{ session_ids: ['session-a'] }])
        expect(logic.values.recentTraces.status).toEqual('ready')
        expect(logic.values.traceTitles.get('trace-b')).toEqual(ready(makeTracePreview('trace-b')))
        expect(logic.values.sessionTitles.get('session-a')).toEqual(ready(makeSessionPreview('session-a')))
        expect(logic.values.traceRows.map((row) => row.traceId)).toEqual(['trace-a', 'trace-b'])

        shellScopeLogic.actions.setDateRange('-30d', null)
        await expectLogic(logic).toFinishAllListeners()

        expect(traceReads.at(-1)).toEqual({ ...RANGE, date_from: '-30d', person_id: LISTED, limit: '5' })
        expect(sessionReads.at(-1)).toEqual({ ...RANGE, date_from: '-30d', person_id: LISTED, limit: '5' })
        expect(peopleReads.filter((read) => read.person_id)).toEqual([])
    })

    it('drops a person read from before a range change, and reads them again in the new range', async () => {
        const [oldRead, releaseOldRead] = held()
        const [newPage, releaseNewPage] = held()
        lookUpHeld = oldRead
        lookUpAnswer = [200, makePersonListItem({ id: UNLISTED, traceCount: 1 })]
        router.actions.push(combineUrl(urls.aiObservabilityUsers(), { person: UNLISTED }).url)
        peopleListLogic.mount()
        await expectLogic(peopleListLogic).toFinishAllListeners()
        logic = personDrawerLogic({ personId: UNLISTED })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPerson'])

        lookUpHeld = null
        lookUpAnswer = [200, makePersonListItem({ id: UNLISTED, traceCount: 9 })]
        pageHeld = newPage
        shellScopeLogic.actions.setDateRange('-30d', null)
        releaseOldRead()
        await expectLogic(logic).toFinishListeners()
        releaseNewPage()
        await expectLogic(logic).toFinishAllListeners()

        expect(peopleReads.filter((read) => read.person_id).map((read) => read.date_from)).toEqual(['-24h', '-30d'])
        expect(logic.values.person).toMatchObject({ id: UNLISTED, traceCount: 9 })
    })

    it("reads the person, their recent traces and sessions, and links to all their traces under the list's property filters", async () => {
        const properties = JSON.stringify([MODEL_FILTER])

        await openPerson(UNLISTED, { filters: [MODEL_FILTER], person_search: 'bo', view: 'new' })

        expect(peopleReads.filter((read) => read.person_id)).toEqual([{ ...RANGE, properties, person_id: UNLISTED }])
        expect(traceReads).toEqual([{ ...RANGE, properties, person_id: UNLISTED, limit: '5' }])
        expect(sessionReads).toEqual([{ ...RANGE, properties, person_id: UNLISTED, limit: '5' }])
        expect(Object.fromEntries(new URL(logic.values.viewAllHref, 'http://localhost').searchParams)).toEqual({
            ...RANGE,
            filters: properties,
            person: UNLISTED,
        })
    })

    it.each<[string, Record<string, string>, () => void]>([
        ['steps to another page', {}, () => peopleListLogic.actions.setOffset(50)],
        ['sorts by cost', {}, () => peopleListLogic.actions.setOrder(AiObservabilityPeopleListOrder.Cost)],
        ['searches for someone else', {}, () => listFiltersLogic(PEOPLE_LIST_FILTERS).actions.setSearch('bo')],
        [
            'hides anonymous people',
            { include_anonymous: 'true' },
            () => peopleListLogic.actions.setIncludeAnonymous(false),
        ],
    ])('keeps showing the person when the list %s and no longer holds them', async (_name, listParams, change) => {
        await openPerson(LISTED, listParams)
        pageAnswer = makePersonListPage(['person-other'])

        change()
        await expectLogic(peopleListLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()

        expect(peopleListLogic.values.items.map((item) => item.id)).toEqual(['person-other'])
        expect(logic.values).toMatchObject({ person: PAGE.results[0], status: 'ready' })
        expect(peopleReads.filter((read) => read.person_id)).toEqual([])
    })

    it('shows a failed read of the person as failed, and reads them again on retry', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        jest.spyOn(posthog, 'captureException')
        lookUpAnswer = [500, { detail: 'boom' }]

        await openPerson(UNLISTED)

        expect(logic.values).toMatchObject({ person: null, status: 'error' })
        expect(capture).toHaveBeenCalledWith('llma person drawer section failed', { section: 'person' })

        lookUpAnswer = [200, makePersonListItem({ id: UNLISTED })]
        logic.actions.loadPerson()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values).toMatchObject({ person: { id: UNLISTED }, status: 'ready' })
    })

    it('settles a person with no sessions as no sessions, without reading titles', async () => {
        sessionsAnswer = [200, makeSessionListPage([])]

        await openPerson(LISTED)

        expect(logic.values.recentSessions).toEqual(ready([]))
        expect(sessionPreviewBodies).toEqual([])
    })

    it('shows a failed section as failed, never as empty, and reads it again on retry', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        jest.spyOn(posthog, 'captureException')
        tracesAnswer = () => [500, { detail: 'boom' }]

        await openPerson(LISTED)

        expect(logic.values.recentTraces).toEqual({ status: 'error' })
        expect(logic.values.recentSessions.status).toEqual('ready')
        expect(capture).toHaveBeenCalledWith('llma person drawer section failed', { section: 'recent_traces' })

        tracesAnswer = () => [200, makeTraceListPage(['trace-a'])]
        logic.actions.loadRecentTraces()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.recentTraces.status).toEqual('ready')
        expect(logic.values.traceRows.map((row) => row.traceId)).toEqual(['trace-a'])
    })

    it('closes a trace opened from a link on Escape before it closes the person', async () => {
        await openPerson(LISTED, { trace: 'trace-a' })

        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

        expect(router.values.searchParams).toMatchObject({ person: LISTED })
        expect(router.values.searchParams.trace).toBeUndefined()

        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

        expect(router.values.searchParams.person).toBeUndefined()
    })
})
