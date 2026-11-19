import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TraceListApi, TraceTurnListApi } from '../../generated/api.schemas'
import { traceDrawerLogic } from '../trace/traceDrawerLogic'
import type { ConversationTurn } from '../trace/types'
import {
    SessionConversationLogicProps,
    SESSION_TURNS_LIST,
    SESSION_TURNS_PAGE_SIZE,
    sessionConversationLogic,
} from './sessionConversationLogic'
import {
    SESSION_TRACES_URL,
    SESSION_TURNS_URL,
    makeSessionListItem,
    makeSessionTurnsPage,
    makeTraceTurn,
} from './testFixtures'

const SESSION = makeSessionListItem({ id: 'session-1' })
const PROPS: SessionConversationLogicProps = {
    sessionId: SESSION.id,
    firstSeen: SESSION.firstSeen,
    lastSeen: SESSION.lastSeen,
    aroundTraceId: null,
}
const FIRST_PAGE_PARAMS = {
    session_id: 'session-1',
    order: 'oldest_first',
    date_from: SESSION.firstSeen,
    date_to: SESSION.lastSeen,
    limit: String(SESSION_TURNS_PAGE_SIZE),
}

type TurnsBody = { trace_ids: string[]; earliest_created_at: string; latest_created_at: string }
type Answer<T> = [number, T | { detail: string }]

describe('sessionConversationLogic', () => {
    let pageRequests: Record<string, string>[]
    let turnRequests: TurnsBody[]
    let answerPage: (params: URLSearchParams) => Answer<TraceListApi>
    let answerTurns: (body: TurnsBody) => Answer<TraceTurnListApi>
    let logic: ReturnType<typeof sessionConversationLogic.build>

    const readyTurns = (): ConversationTurn[] => {
        const { turns } = logic.values
        if (turns.status !== 'ready') {
            throw new Error(`expected ready turns, got ${turns.status}`)
        }
        return turns.turns
    }

    async function mount(props: Partial<SessionConversationLogicProps> = {}): Promise<void> {
        logic = sessionConversationLogic({ ...PROPS, ...props })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        pageRequests = []
        turnRequests = []
        answerPage = () => [200, makeSessionTurnsPage([1, 2], { nextCursor: 'cursor-next' })]
        answerTurns = (body) => [200, { items: body.trace_ids.map((traceId) => makeTraceTurn(traceId)) }]
        useMocks({
            get: {
                [SESSION_TRACES_URL]: ({ request }) => {
                    const params = new URL(request.url).searchParams
                    pageRequests.push(Object.fromEntries(params))
                    return answerPage(params)
                },
            },
            post: {
                [SESSION_TURNS_URL]: async ({ request }: { request: Request }) => {
                    const body: TurnsBody = await request.json()
                    turnRequests.push(body)
                    return answerTurns(body)
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

    it('first page reads oldest first in the session window', async () => {
        const capture = jest.spyOn(posthog, 'capture')

        await mount()

        expect(pageRequests).toEqual([FIRST_PAGE_PARAMS])
        expect(readyTurns().map((turn) => turn.id)).toEqual(['trace-1', 'trace-2'])
        expect(logic.values.rows.map(({ traceId, stepId, defaultStepId }) => [traceId, stepId, defaultStepId])).toEqual(
            [
                ['trace-1', null, 'trace-1-gen'],
                ['trace-2', null, 'trace-2-gen'],
            ]
        )
        expect(logic.values).toMatchObject({ olderEdge: 'end', newerEdge: 'more' })
        expect(capture).toHaveBeenCalledWith('llma session conversation loaded', {
            rows_wait_ms: expect.any(Number),
            turns_wait_ms: expect.any(Number),
            turn_count: 2,
            opened_around: false,
        })
    })

    it('turns read follows the rows', async () => {
        const page = makeSessionTurnsPage([1, 2, 3])
        page.items[0] = { ...page.items[0], totals: { ...page.items[0].totals, latencyMs: 18_000 } }
        page.items[2] = { ...page.items[2], firstError: 'RateLimitError: slow down' }
        answerPage = () => [200, page]
        answerTurns = () => [
            200,
            {
                items: [
                    makeTraceTurn('trace-1'),
                    makeTraceTurn('trace-2', { input: null, inputMissingReason: 'too_large' }),
                ],
            },
        ]

        await mount()

        expect(turnRequests).toEqual([
            {
                trace_ids: ['trace-1', 'trace-2', 'trace-3'],
                earliest_created_at: page.items[0].createdAt,
                latest_created_at: page.items[2].createdAt,
            },
        ])
        const [first, second, third] = readyTurns()
        expect(first).toMatchObject({
            id: 'trace-1',
            timestamp: page.items[0].createdAt,
            waitMs: 18_000,
            error: null,
            input: makeTraceTurn('trace-1').input,
            output: makeTraceTurn('trace-1').output,
        })
        expect(first.pending).toBeUndefined()
        expect(second).toMatchObject({
            input: { kind: 'messages', messages: [] },
            missingReasons: { input: 'too_large', output: null },
        })
        expect(third).toMatchObject({ error: 'RateLimitError: slow down', input: { kind: 'messages', messages: [] } })
        expect(third.pending).toBeUndefined()
    })

    it('scroll near end loads newer', async () => {
        answerPage = (params) =>
            params.get('cursor') === 'cursor-next'
                ? [200, makeSessionTurnsPage([3])]
                : [200, makeSessionTurnsPage([1, 2], { nextCursor: 'cursor-next' })]
        await mount()

        logic.actions.loadNewer()
        await expectLogic(logic).toFinishAllListeners()

        expect(pageRequests[1]).toEqual({ ...FIRST_PAGE_PARAMS, cursor: 'cursor-next' })
        expect(readyTurns().map((turn) => turn.id)).toEqual(['trace-1', 'trace-2', 'trace-3'])
        expect(turnRequests.map((body) => body.trace_ids)).toEqual([['trace-1', 'trace-2'], ['trace-3']])
        expect(logic.values.newerEdge).toEqual('end')

        logic.actions.loadNewer()
        await expectLogic(logic).toFinishAllListeners()
        expect(pageRequests).toHaveLength(2)
    })

    it('around opens a page holding the trace and can load older', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        answerPage = (params) =>
            params.get('before_cursor') === 'cursor-before'
                ? [200, makeSessionTurnsPage([1, 2], { nextCursor: 'cursor-unused' })]
                : [200, makeSessionTurnsPage([3, 4], { previousCursor: 'cursor-before' })]

        await mount({ aroundTraceId: 'trace-4' })
        expect(pageRequests).toEqual([{ ...FIRST_PAGE_PARAMS, around: 'trace-4' }])
        expect(logic.values).toMatchObject({ olderEdge: 'more', newerEdge: 'end' })
        expect(capture).toHaveBeenCalledWith(
            'llma session conversation loaded',
            expect.objectContaining({ opened_around: true })
        )

        logic.actions.loadOlder()
        await expectLogic(logic).toFinishAllListeners()

        expect(pageRequests[1]).toEqual({ ...FIRST_PAGE_PARAMS, before_cursor: 'cursor-before' })
        expect(readyTurns().map((turn) => turn.id)).toEqual(['trace-1', 'trace-2', 'trace-3', 'trace-4'])
        expect(logic.values).toMatchObject({ olderEdge: 'end', newerEdge: 'end' })
    })

    it('a trace outside the session opens the session from its first turn', async () => {
        answerPage = (params) =>
            params.has('around')
                ? [400, { detail: 'The trace is not in this session.' }]
                : [200, makeSessionTurnsPage([1, 2])]

        await mount({ aroundTraceId: 'trace-elsewhere' })

        expect(pageRequests).toEqual([{ ...FIRST_PAGE_PARAMS, around: 'trace-elsewhere' }, FIRST_PAGE_PARAMS])
        expect(readyTurns().map((turn) => turn.id)).toEqual(['trace-1', 'trace-2'])
    })

    async function openTurnAt(traceId: string): Promise<void> {
        router.actions.push(combineUrl(urls.aiObservabilitySessions(), { session: SESSION.id, trace: traceId }).url)
        await expectLogic(logic).toFinishAllListeners()
    }

    async function mountOnSessionsPath(): Promise<void> {
        router.actions.push(combineUrl(urls.aiObservabilitySessions(), { session: SESSION.id }).url)
        await mount()
    }

    it('the drawer on the last loaded turn loads the next page, so it can step on', async () => {
        answerPage = (params) =>
            params.has('cursor')
                ? [200, makeSessionTurnsPage([9])]
                : [200, makeSessionTurnsPage([1, 2], { nextCursor: 'cursor-next' })]
        await mountOnSessionsPath()

        await openTurnAt('trace-2')

        expect(pageRequests).toEqual([FIRST_PAGE_PARAMS, { ...FIRST_PAGE_PARAMS, cursor: 'cursor-next' }])
        expect(logic.values.rows.map((row) => row.traceId)).toEqual(['trace-1', 'trace-2', 'trace-9'])
    })

    it.each([
        ['the first', 'trace-1'],
        ['a middle', 'trace-2'],
    ])('opening %s loaded turn loads no earlier page', async (_name, traceId) => {
        answerPage = () => [
            200,
            makeSessionTurnsPage([1, 2, 3], { nextCursor: 'cursor-next', previousCursor: 'cursor-before' }),
        ]
        await mountOnSessionsPath()

        await openTurnAt(traceId)

        expect(pageRequests).toEqual([FIRST_PAGE_PARAMS])
    })

    it('stepping up from the first loaded turn loads the earlier page and opens the turn before it', async () => {
        answerPage = (params) =>
            params.has('before_cursor')
                ? [200, makeSessionTurnsPage([0])]
                : [200, makeSessionTurnsPage([1, 2], { previousCursor: 'cursor-before' })]
        await mountOnSessionsPath()
        await openTurnAt('trace-1')

        traceDrawerLogic({ listId: SESSION_TURNS_LIST }).actions.stepTo('previous')
        await expectLogic(logic).toFinishAllListeners()

        expect(pageRequests).toEqual([FIRST_PAGE_PARAMS, { ...FIRST_PAGE_PARAMS, before_cursor: 'cursor-before' }])
        expect(readyTurns().map((turn) => turn.id)).toEqual(['trace-0', 'trace-1', 'trace-2'])
        expect(router.values.searchParams).toMatchObject({ session: SESSION.id, trace: 'trace-0' })
    })

    it('a failed turns read shows an error per turn, not an empty turn', async () => {
        silenceKeaLoadersErrors()
        answerTurns = () => [500, { detail: 'boom' }]
        await mount()

        expect(readyTurns().map((turn) => turn.pending)).toEqual(['error', 'error'])

        answerTurns = (body) => [200, { items: body.trace_ids.map((traceId) => makeTraceTurn(traceId)) }]
        logic.actions.retryTurns()
        await expectLogic(logic).toFinishAllListeners()

        expect(turnRequests.map((body) => body.trace_ids)).toEqual([
            ['trace-1', 'trace-2'],
            ['trace-1', 'trace-2'],
        ])
        expect(readyTurns().map((turn) => turn.pending)).toEqual([undefined, undefined])
    })

    it('a failed first page shows the error in place and reads again on reload', async () => {
        silenceKeaLoadersErrors()
        answerPage = () => [500, { detail: 'boom' }]
        await mount()

        expect(logic.values.turns.status).toEqual('error')

        answerPage = () => [200, makeSessionTurnsPage([1])]
        logic.actions.reload()
        await expectLogic(logic).toFinishAllListeners()

        expect(readyTurns().map((turn) => turn.id)).toEqual(['trace-1'])
    })
})
