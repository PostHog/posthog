import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { SessionListApi, SessionListItemApi } from '../../generated/api.schemas'
import { listFiltersLogic } from '../lists/listFiltersLogic'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { SESSIONS_LIST_FILTERS, sessionsListLogic } from './sessionsListLogic'
import { makeSessionListItem, makeSessionListPage } from './testFixtures'

const SESSIONS_URL = '/api/projects/:team_id/ai_observability/sessions/'
const SESSION_URL = '/api/projects/:team_id/ai_observability/sessions/:id/'
const UNLISTED_ID = 'session/z?'
const UNLISTED_SEGMENT = 'c2Vzc2lvbi96Pw'
const LINK_TIMESTAMP = '2026-08-01T10:00:00Z'
const LIST_PATH = urls.aiObservabilitySessions()
const FIRST_PAGE = makeSessionListPage(['session-a', 'session-b'], { nextCursor: 'cursor-2' })
const SECOND_PAGE = makeSessionListPage(['session-c'])
const FIRST_PAGE_PARAMS = { date_from: '-7d', filter_test_accounts: 'false', limit: '50' }
const SEARCH_FLAG = FEATURE_FLAGS.LLM_OBSERVABILITY_TRACE_SEARCH
const MODEL_FILTER: AnyPropertyFilter = {
    key: '$ai_model',
    value: ['gpt-4'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

type Answer = [number, SessionListApi | { detail: string }]
type SessionAnswer = [number, SessionListItemApi | { detail: string }]

describe('sessionsListLogic', () => {
    let requests: Record<string, string>[] = []
    let answer: (params: URLSearchParams) => Answer
    let sessionReads: { id: string; params: Record<string, string> }[] = []
    let sessionAnswer: SessionAnswer
    let logic: ReturnType<typeof sessionsListLogic.build>

    const ids = (): string[] => logic.values.items.map((item) => item.id)

    async function mountAt(url: string, flags: string[] = []): Promise<void> {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
        router.actions.push(url)
        logic = sessionsListLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        localStorage.clear()
        requests = []
        sessionReads = []
        answer = (params) => [200, params.get('cursor') === 'cursor-2' ? SECOND_PAGE : FIRST_PAGE]
        sessionAnswer = [200, makeSessionListItem({ id: UNLISTED_ID })]
        useMocks({
            get: {
                [SESSIONS_URL]: ({ request }) => {
                    const params = new URL(request.url).searchParams
                    requests.push(Object.fromEntries(params))
                    return answer(params)
                },
                [SESSION_URL]: ({ request, params }) => {
                    sessionReads.push({
                        id: String(params.id),
                        params: Object.fromEntries(new URL(request.url).searchParams),
                    })
                    return sessionAnswer
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic.unmount()
        resumeKeaLoadersErrors()
        jest.restoreAllMocks()
    })

    it('loads the first page on mount', async () => {
        const capture = jest.spyOn(posthog, 'capture')

        await mountAt(LIST_PATH)

        expect(requests).toEqual([FIRST_PAGE_PARAMS])
        expect(ids()).toEqual(['session-a', 'session-b'])
        expect(logic.values).toMatchObject({ state: 'ready', canShowNext: true, canShowPrevious: false })
        expect(capture).toHaveBeenCalledWith('llma sessions list loaded', {
            rows_wait_ms: expect.any(Number),
            row_count: 2,
            date_from: '-7d',
            searched: false,
        })
    })

    it.each([
        ['sends', [SEARCH_FLAG], { search: 'refund' }],
        ['leaves out', [], {}],
    ])('%s the search in the url by the search flag, and never the trace view', async (_name, flags, search) => {
        await mountAt(
            `${LIST_PATH}?filters=${encodeURIComponent(JSON.stringify([MODEL_FILTER]))}&view=errors&trace_search=refund`,
            flags
        )

        expect(requests).toEqual([{ ...FIRST_PAGE_PARAMS, properties: JSON.stringify([MODEL_FILTER]), ...search }])
    })

    it('next page uses nextCursor and keeps the pages it has', async () => {
        await mountAt(LIST_PATH)

        logic.actions.showNextPage()
        await expectLogic(logic).toFinishAllListeners()
        expect(requests[1]).toEqual({ ...FIRST_PAGE_PARAMS, cursor: 'cursor-2' })
        expect(ids()).toEqual(['session-c'])
        expect(logic.values).toMatchObject({ canShowNext: false, canShowPrevious: true })

        logic.actions.showPreviousPage()
        expect(ids()).toEqual(['session-a', 'session-b'])
        expect(requests).toHaveLength(2)
    })

    it.each([
        [
            'a filter',
            () => listFiltersLogic(SESSIONS_LIST_FILTERS).actions.setPropertyFilters([MODEL_FILTER]),
            { ...FIRST_PAGE_PARAMS, properties: JSON.stringify([MODEL_FILTER]) },
        ],
        [
            'the date range',
            () => shellScopeLogic.actions.setDateRange('-24h', null),
            { ...FIRST_PAGE_PARAMS, date_from: '-24h' },
        ],
    ])('filters change resets to first page when %s changes', async (_name, change, params) => {
        await mountAt(LIST_PATH)
        logic.actions.showNextPage()
        await expectLogic(logic).toFinishAllListeners()

        change()
        expect(logic.values).toMatchObject({ items: [], state: 'loading', pageIndex: 0 })

        await expectLogic(logic).toFinishAllListeners()
        expect(requests.at(-1)).toEqual(params)
        expect(ids()).toEqual(['session-a', 'session-b'])
    })

    it('openSession and the session link carry the session and its start, drop drawer params and push', async () => {
        await mountAt(`${LIST_PATH}?trace=trace-9&ts=2026-09-01T10:00:00Z&step=gen-1&date_from=-7d`)
        expect(logic.values.openSessionId).toBeNull()
        const session = makeSessionListItem({ id: 'session-b', firstSeen: LINK_TIMESTAMP })
        const opened = { session: 'session-b', timestamp: LINK_TIMESTAMP, date_from: '-7d' }
        const href = combineUrl(logic.values.sessionHref(session))
        expect(href.pathname).toContain(LIST_PATH)
        expect(href.searchParams).toEqual(opened)

        await expectLogic(router, () => logic.actions.openSession(session)).toDispatchActions(['push'])

        expect(router.values.searchParams).toEqual(opened)
        expect(logic.values.openSessionId).toEqual('session-b')
        expect(logic.values.openSessionTimestamp).toEqual('2026-08-01T10:00:00.000Z')

        await expectLogic(router, () => logic.actions.openSession(null)).toDispatchActions(['push'])

        expect(router.values.searchParams).toEqual({ date_from: '-7d' })
        expect(logic.values.openSessionId).toBeNull()
    })

    const UNLISTED_READ = { id: UNLISTED_SEGMENT, params: { timestamp_hint: '2026-08-01T10:00:00.000Z' } }

    it.each<[string, string, SessionAnswer, string, string | null, (typeof UNLISTED_READ)[]]>([
        ['a listed session', 'session-b', [200, makeSessionListItem()], 'ready', 'session-b', []],
        [
            'a session the list does not show',
            UNLISTED_ID,
            [200, makeSessionListItem({ id: UNLISTED_ID })],
            'ready',
            UNLISTED_ID,
            [UNLISTED_READ],
        ],
        [
            'a session that does not exist',
            UNLISTED_ID,
            [404, { detail: 'Session not found.' }],
            'not_found',
            null,
            [UNLISTED_READ],
        ],
        ['a session whose read fails', UNLISTED_ID, [500, { detail: 'boom' }], 'failed', null, [UNLISTED_READ]],
    ])('opens %s from a link', async (_name, sessionId, read, status, openId, reads) => {
        jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
        sessionAnswer = read

        await mountAt(combineUrl(LIST_PATH, { session: sessionId, timestamp: LINK_TIMESTAMP }).url)

        expect(logic.values.openSessionStatus).toEqual(status)
        expect(logic.values.openItem?.id ?? null).toEqual(openId)
        expect(sessionReads).toEqual(reads)
    })

    it.each<[string, () => void]>([
        ['the list reloads', () => logic.actions.reload()],
        [
            'the session is opened again',
            () => {
                const link = router.values.location
                logic.actions.openSession(null)
                router.actions.push(`${link.pathname}${link.search}`)
            },
        ],
    ])('reads again a session whose read failed when %s', async (_name, retry) => {
        jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
        sessionAnswer = [500, { detail: 'boom' }]
        await mountAt(combineUrl(LIST_PATH, { session: UNLISTED_ID, timestamp: LINK_TIMESTAMP }).url)
        expect(logic.values.openSessionStatus).toEqual('failed')
        sessionAnswer = [200, makeSessionListItem({ id: UNLISTED_ID })]

        retry()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.openSessionStatus).toEqual('ready')
        expect(logic.values.openItem?.id).toEqual(UNLISTED_ID)
    })

    it('opens a session whose link carries a malformed time without sending the time', async () => {
        await mountAt(combineUrl(LIST_PATH, { session: UNLISTED_ID, timestamp: 'not-a-date' }).url)

        expect(sessionReads).toEqual([{ id: UNLISTED_SEGMENT, params: {} }])
        expect(logic.values.openSessionStatus).toEqual('ready')
    })

    it('keeps the open session open when a filter takes it off the list', async () => {
        await mountAt(combineUrl(LIST_PATH, { session: 'session-b' }).url)
        answer = () => [200, SECOND_PAGE]

        listFiltersLogic(SESSIONS_LIST_FILTERS).actions.setPropertyFilters([MODEL_FILTER])
        await expectLogic(logic).toFinishAllListeners()

        expect(ids()).toEqual(['session-c'])
        expect(logic.values.openItem?.id).toEqual('session-b')
        expect(sessionReads).toHaveLength(0)
    })

    it('reads the open session from the url only on the sessions path', async () => {
        await mountAt(`${urls.aiObservabilityTraces()}?session=session-b`)

        expect(logic.values.openSessionId).toBeNull()
    })

    it('shows the error when the first page fails with nothing on screen', async () => {
        silenceKeaLoadersErrors()
        const toastError = jest.spyOn(lemonToast, 'error')
        answer = () => [500, { detail: 'boom' }]

        await mountAt(LIST_PATH)

        expect(logic.values).toMatchObject({ items: [], state: 'error' })
        expect(toastError).not.toHaveBeenCalled()
    })

    it.each([
        ['nothing narrows the selection', '', 'empty'],
        ['a property filter is on', `filters=${encodeURIComponent(JSON.stringify([MODEL_FILTER]))}`, 'empty-filtered'],
        ['a search is on', 'trace_search=refund', 'empty-filtered'],
        ['test accounts are filtered out', 'filter_test_accounts=true', 'empty-filtered'],
    ])('shows an empty first page as %s', async (_name, query, state) => {
        answer = () => [200, makeSessionListPage([])]

        await mountAt(`${LIST_PATH}?${query}`, [SEARCH_FLAG])

        expect(logic.values.state).toEqual(state)
    })
})
