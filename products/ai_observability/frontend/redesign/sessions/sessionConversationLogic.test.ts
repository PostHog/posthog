import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SessionTurnPageApi, TraceTurnListApi, TraceTurnsRequestApi } from '../../generated/api.schemas'
import { traceDrawerLogic } from '../trace/traceDrawerLogic'
import {
    SessionConversationLogicProps,
    SESSION_TURNS_LIST,
    SESSION_TURNS_PAGE_SIZE,
    sessionConversationLogic,
} from './sessionConversationLogic'
import { SESSION_TURNS_URL, TRACE_TURNS_URL, makeSessionTurnPage, makeTraceTurn } from './testFixtures'

const SESSION_ID = 'session/1'
const SESSION_SEGMENT = 'c2Vzc2lvbi8x'
const PROPS: SessionConversationLogicProps = { sessionId: SESSION_ID, timestamp: null, aroundTraceId: null }
const FIRST_PAGE_PARAMS = { limit: String(SESSION_TURNS_PAGE_SIZE) }

type Answer = [number, SessionTurnPageApi | { detail: string }]
type SidesAnswer = [number, TraceTurnListApi | { detail: string }]

function answerEveryTurn(body: TraceTurnsRequestApi): SidesAnswer {
    return [200, { items: body.trace_ids.map((traceId) => makeTraceTurn(traceId)) }]
}

describe('sessionConversationLogic', () => {
    let pageRequests: Record<string, string>[]
    let answerPage: (params: URLSearchParams) => Answer | Promise<Answer>
    let sidesRequests: TraceTurnsRequestApi[]
    let answerSides: (body: TraceTurnsRequestApi) => SidesAnswer | Promise<SidesAnswer>
    let logic: ReturnType<typeof sessionConversationLogic.build>

    const turnIds = (): string[] => logic.values.turns.map((turn) => turn.id)
    const sidesStatuses = (): (string | undefined)[] => logic.values.turns.map((turn) => turn.sidesStatus)

    async function mount(props: Partial<SessionConversationLogicProps> = {}): Promise<void> {
        logic = sessionConversationLogic({ ...PROPS, ...props })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    async function settle(): Promise<void> {
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        pageRequests = []
        sidesRequests = []
        answerPage = () => [200, makeSessionTurnPage([1, 2], { nextCursor: 'cursor-next' })]
        answerSides = answerEveryTurn
        useMocks({
            get: {
                [SESSION_TURNS_URL]: ({ request, params }) => {
                    const search = new URL(request.url).searchParams
                    pageRequests.push(params.id === SESSION_SEGMENT ? Object.fromEntries(search) : { wrongId: 'true' })
                    return answerPage(search)
                },
            },
            post: {
                [TRACE_TURNS_URL]: async ({ request }: { request: Request }) => {
                    const body: TraceTurnsRequestApi = await request.json()
                    sidesRequests.push(body)
                    return answerSides(body)
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

    it("reads the session's turns, then their messages by trace id", async () => {
        const capture = jest.spyOn(posthog, 'capture')
        const page = makeSessionTurnPage([1, 2, 3], { nextCursor: 'cursor-next' })
        page.items[0] = {
            ...page.items[0],
            totals: { ...page.items[0].totals, latencyMs: 18_000 },
            waitSlow: true,
            silenceBeforeMs: 90_000,
        }
        page.items[2] = { ...page.items[2], firstError: 'RateLimitError: slow down' }
        answerPage = () => [200, page]
        answerSides = (body) => [
            200,
            {
                items: body.trace_ids.map((traceId) =>
                    traceId === 'trace-2'
                        ? makeTraceTurn(traceId, { input: null, inputMissingReason: 'too_large' })
                        : makeTraceTurn(traceId)
                ),
            },
        ]

        await mount({ timestamp: '2026-08-01T10:00:00.000Z' })

        expect(pageRequests).toEqual([{ ...FIRST_PAGE_PARAMS, timestamp_hint: '2026-08-01T10:00:00.000Z' }])
        expect(sidesRequests).toEqual([
            {
                trace_ids: ['trace-1', 'trace-2', 'trace-3'],
                earliest_created_at: page.items[0].createdAt,
                latest_created_at: page.items[2].createdAt,
            },
        ])
        const [first, second, third] = logic.values.turns
        expect(first).toEqual({
            id: 'trace-1',
            timestamp: page.items[0].createdAt,
            waitMs: 18_000,
            waitSlow: true,
            silenceBeforeMs: 90_000,
            error: null,
            trace: { name: page.items[0].name, totals: page.items[0].totals },
            input: makeTraceTurn('trace-1').input,
            output: makeTraceTurn('trace-1').output,
            sidesStatus: 'ready',
        })
        expect(second).toMatchObject({
            input: { kind: 'messages', messages: [] },
            missingReasons: { input: 'too_large', output: null },
        })
        expect(third).toMatchObject({ error: 'RateLimitError: slow down', output: makeTraceTurn('trace-3').output })
        expect(logic.values.rows.map(({ traceId, stepId, defaultStepId }) => [traceId, stepId, defaultStepId])).toEqual(
            [
                ['trace-1', null, 'trace-1-gen'],
                ['trace-2', null, 'trace-2-gen'],
                ['trace-3', null, 'trace-3-gen'],
            ]
        )
        expect(logic.values.rows[0].overview).toMatchObject({ id: 'trace-1', totals: { latencyMs: 18_000 } })
        expect(logic.values).toMatchObject({ status: 'ready', olderEdge: 'end', newerEdge: 'more' })
        expect(capture).toHaveBeenCalledWith('llma session conversation loaded', {
            turns_wait_ms: expect.any(Number),
            turn_count: 3,
            opened_around: false,
        })

        logic.actions.reload()
        await settle()

        expect(capture.mock.calls.filter(([event]) => event === 'llma session conversation loaded')).toHaveLength(1)
    })

    it('shows the turns while their messages load', async () => {
        let releaseSides: () => void = () => {}
        const sidesReleased = new Promise<void>((resolve) => {
            releaseSides = resolve
        })
        answerSides = async (body) => {
            await sidesReleased
            return answerEveryTurn(body)
        }

        logic = sessionConversationLogic(PROPS)
        logic.mount()
        await expectLogic(logic).toDispatchActions(['sidesRequested'])

        expect(logic.values.status).toEqual('ready')
        expect(turnIds()).toEqual(['trace-1', 'trace-2'])
        expect(sidesStatuses()).toEqual(['loading', 'loading'])

        releaseSides()
        await settle()

        expect(sidesStatuses()).toEqual(['ready', 'ready'])
    })

    it('marks the turns of a failed messages read as failed, and a retry reads them again', async () => {
        jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
        answerSides = () => [500, { detail: 'boom' }]
        await mount()

        expect(sidesStatuses()).toEqual(['error', 'error'])
        expect(logic.values.turns[0].input).toEqual({ kind: 'messages', messages: [] })

        answerSides = answerEveryTurn
        logic.actions.retrySides()
        await settle()

        expect(sidesRequests.map((body) => body.trace_ids)).toEqual([
            ['trace-1', 'trace-2'],
            ['trace-1', 'trace-2'],
        ])
        expect(sidesStatuses()).toEqual(['ready', 'ready'])
    })

    it('a retry reads the failed batches one after another', async () => {
        jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
        const page = makeSessionTurnPage([1, 2])
        page.items[1] = { ...page.items[1], createdAt: '2026-11-01T10:15:00.000Z' }
        answerPage = () => [200, page]
        answerSides = () => [500, { detail: 'boom' }]
        await mount()
        const reads: string[] = []
        answerSides = async (body) => {
            reads.push(`asked ${body.trace_ids}`)
            // Yields, so a batch sent at the same time would be asked for before this one answers.
            await new Promise((resolve) => setTimeout(resolve, 0))
            reads.push(`answered ${body.trace_ids}`)
            return answerEveryTurn(body)
        }

        logic.actions.retrySides()
        expect(sidesStatuses()).toEqual(['loading', 'loading'])
        await settle()

        expect(reads).toEqual(['asked trace-1', 'answered trace-1', 'asked trace-2', 'answered trace-2'])
        expect(sidesStatuses()).toEqual(['ready', 'ready'])
    })

    it('unmounting aborts the messages still loading, and reports no failure', async () => {
        const captureException = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
        const fetched = jest.spyOn(window, 'fetch')
        answerSides = () => new Promise<SidesAnswer>(() => {})
        logic = sessionConversationLogic(PROPS)
        logic.mount()
        await expectLogic(logic).toDispatchActions(['sidesRequested'])
        const sidesCall = fetched.mock.calls.find((call: Parameters<typeof fetch>) =>
            String(call[0]).includes('/traces/turns/')
        )
        const sidesSignal = sidesCall?.[1]?.signal

        logic.unmount()
        await new Promise(process.nextTick)

        expect(sidesSignal?.aborted).toBe(true)
        expect(captureException).not.toHaveBeenCalled()
        answerSides = answerEveryTurn
        await mount()
    })

    it('shows a turn the messages read leaves out as read, with nothing in it', async () => {
        answerSides = () => [200, { items: [makeTraceTurn('trace-1')] }]
        await mount()

        expect(sidesStatuses()).toEqual(['ready', 'ready'])
        expect(logic.values.turns[1]).toMatchObject({
            input: { kind: 'messages', messages: [] },
            output: { kind: 'messages', messages: [] },
        })
    })

    it('loads newer pages and their messages until the last one', async () => {
        answerPage = (params) =>
            params.get('cursor') === 'cursor-next'
                ? [200, makeSessionTurnPage([3])]
                : [200, makeSessionTurnPage([1, 2], { nextCursor: 'cursor-next' })]
        await mount()

        logic.actions.loadNewer()
        await settle()

        expect(pageRequests[1]).toEqual({ ...FIRST_PAGE_PARAMS, cursor: 'cursor-next' })
        expect(turnIds()).toEqual(['trace-1', 'trace-2', 'trace-3'])
        expect(sidesRequests.map((body) => body.trace_ids)).toEqual([['trace-1', 'trace-2'], ['trace-3']])
        expect(logic.values.newerEdge).toEqual('end')

        logic.actions.loadNewer()
        await settle()
        expect(pageRequests).toHaveLength(2)
    })

    it('around opens a page holding the trace and can load older', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        answerPage = (params) =>
            params.get('before_cursor') === 'cursor-before'
                ? [200, makeSessionTurnPage([1, 2], { nextCursor: 'cursor-unused' })]
                : [200, makeSessionTurnPage([3, 4], { previousCursor: 'cursor-before' })]

        await mount({ aroundTraceId: 'trace-4' })
        expect(pageRequests).toEqual([{ ...FIRST_PAGE_PARAMS, around: 'trace-4' }])
        expect(logic.values).toMatchObject({ olderEdge: 'more', newerEdge: 'end' })
        expect(capture).toHaveBeenCalledWith(
            'llma session conversation loaded',
            expect.objectContaining({ opened_around: true })
        )

        logic.actions.loadOlder()
        await settle()

        expect(pageRequests[1]).toEqual({ ...FIRST_PAGE_PARAMS, before_cursor: 'cursor-before' })
        expect(turnIds()).toEqual(['trace-1', 'trace-2', 'trace-3', 'trace-4'])
        expect(logic.values).toMatchObject({ olderEdge: 'end', newerEdge: 'end' })
    })

    it('pages loaded both ways merge in session order without duplicates', async () => {
        answerPage = (params) => {
            if (params.has('before_cursor')) {
                return [200, makeSessionTurnPage([2, 3])]
            }
            if (params.has('cursor')) {
                return [200, makeSessionTurnPage([4, 5])]
            }
            return [200, makeSessionTurnPage([3, 4], { previousCursor: 'cursor-before', nextCursor: 'cursor-next' })]
        }
        await mount({ aroundTraceId: 'trace-4' })

        logic.actions.loadNewer()
        await settle()
        logic.actions.loadOlder()
        await settle()

        expect(turnIds()).toEqual(['trace-2', 'trace-3', 'trace-4', 'trace-5'])
        expect(logic.values.rows.map((row) => row.traceId)).toEqual(['trace-2', 'trace-3', 'trace-4', 'trace-5'])
    })

    it('a failed page shows failed turns with retry, never empty', async () => {
        silenceKeaLoadersErrors()
        answerPage = () => [500, { detail: 'boom' }]
        await mount()

        expect(logic.values.status).toEqual('failed')

        answerPage = (params) =>
            params.has('cursor') ? [500, { detail: 'boom' }] : [200, makeSessionTurnPage([1], { nextCursor: 'c-2' })]
        logic.actions.reload()
        await settle()
        logic.actions.loadNewer()
        await settle()

        expect(logic.values.status).toEqual('ready')
        expect(turnIds()).toEqual(['trace-1'])
        expect(logic.values.newerEdge).toEqual('failed')

        answerPage = () => [200, makeSessionTurnPage([2])]
        logic.actions.loadNewer()
        await settle()

        expect(turnIds()).toEqual(['trace-1', 'trace-2'])
        expect(logic.values.newerEdge).toEqual('end')
    })

    it('a session the turns read does not find shows as not found', async () => {
        silenceKeaLoadersErrors()
        answerPage = () => [404, { detail: 'Session not found.' }]

        await mount()

        expect(logic.values.status).toEqual('not_found')
    })

    it('a failed reload of turns already on screen shows the failure', async () => {
        silenceKeaLoadersErrors()
        await mount()

        answerPage = () => [500, { detail: 'boom' }]
        logic.actions.reload()
        await settle()

        expect(logic.values.status).toEqual('failed')
    })

    async function openTurnAt(traceId: string): Promise<void> {
        router.actions.push(combineUrl(urls.aiObservabilitySessions(), { session: SESSION_ID, trace: traceId }).url)
        await settle()
    }

    async function mountOnSessionsPath(): Promise<void> {
        router.actions.push(combineUrl(urls.aiObservabilitySessions(), { session: SESSION_ID }).url)
        await mount()
    }

    it('the drawer on the last loaded turn loads the next page, so it can step on', async () => {
        answerPage = (params) =>
            params.has('cursor')
                ? [200, makeSessionTurnPage([9])]
                : [200, makeSessionTurnPage([1, 2], { nextCursor: 'cursor-next' })]
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
            makeSessionTurnPage([1, 2, 3], { nextCursor: 'cursor-next', previousCursor: 'cursor-before' }),
        ]
        await mountOnSessionsPath()

        await openTurnAt(traceId)

        expect(pageRequests).toEqual([FIRST_PAGE_PARAMS])
    })

    it('stepping up from the first loaded turn loads the earlier page and opens the turn before it', async () => {
        answerPage = (params) =>
            params.has('before_cursor')
                ? [200, makeSessionTurnPage([0])]
                : [200, makeSessionTurnPage([1, 2], { previousCursor: 'cursor-before' })]
        await mountOnSessionsPath()
        await openTurnAt('trace-1')

        traceDrawerLogic({ listId: SESSION_TURNS_LIST }).actions.stepTo('previous')
        await settle()

        expect(pageRequests).toEqual([FIRST_PAGE_PARAMS, { ...FIRST_PAGE_PARAMS, before_cursor: 'cursor-before' }])
        expect(turnIds()).toEqual(['trace-0', 'trace-1', 'trace-2'])
        expect(router.values.searchParams).toMatchObject({ session: SESSION_ID, trace: 'trace-0' })
    })

    it('a step up reads the earlier page again after that read failed', async () => {
        silenceKeaLoadersErrors()
        answerPage = (params) =>
            params.has('before_cursor')
                ? [500, { detail: 'boom' }]
                : [200, makeSessionTurnPage([1, 2], { previousCursor: 'cursor-before' })]
        await mountOnSessionsPath()
        await openTurnAt('trace-1')
        const drawer = traceDrawerLogic({ listId: SESSION_TURNS_LIST })
        drawer.actions.stepTo('previous')
        await settle()
        expect(logic.values.olderEdge).toEqual('failed')

        answerPage = () => [200, makeSessionTurnPage([0])]
        drawer.actions.stepTo('previous')
        await settle()

        expect(turnIds()).toEqual(['trace-0', 'trace-1', 'trace-2'])
        expect(router.values.searchParams).toMatchObject({ session: SESSION_ID, trace: 'trace-0' })
    })

    it.each<[string, Record<string, string>]>([
        ['closes the drawer', {}],
        ['opens another turn', { trace: 'trace-2' }],
    ])('a step up opens no turn when the person %s before the earlier turns land', async (_name, drawerParams) => {
        let releaseOlder: () => void = () => {}
        const olderReleased = new Promise<void>((resolve) => {
            releaseOlder = resolve
        })
        answerPage = async (params) => {
            if (!params.has('before_cursor')) {
                return [200, makeSessionTurnPage([1, 2], { previousCursor: 'cursor-before' })]
            }
            await olderReleased
            return [200, makeSessionTurnPage([0])]
        }
        await mountOnSessionsPath()
        await openTurnAt('trace-1')
        traceDrawerLogic({ listId: SESSION_TURNS_LIST }).actions.stepTo('previous')
        await expectLogic(logic).toDispatchActions(['loadConversationPage'])

        const afterStep = { session: SESSION_ID, ...drawerParams }
        router.actions.push(combineUrl(urls.aiObservabilitySessions(), afterStep).url)
        releaseOlder()
        await settle()

        expect(turnIds()).toEqual(['trace-0', 'trace-1', 'trace-2'])
        expect(router.values.searchParams).toEqual(afterStep)
    })

    it('a step up that a reload supersedes opens no turn when earlier turns load later', async () => {
        let olderReads = 0
        answerPage = (params) => {
            if (!params.has('before_cursor')) {
                return [200, makeSessionTurnPage([1, 2], { previousCursor: 'cursor-before' })]
            }
            olderReads += 1
            // The first earlier page never answers, as one the reload aborts.
            return olderReads === 1 ? new Promise<Answer>(() => {}) : [200, makeSessionTurnPage([0])]
        }
        await mountOnSessionsPath()
        await openTurnAt('trace-1')
        traceDrawerLogic({ listId: SESSION_TURNS_LIST }).actions.stepTo('previous')

        logic.actions.reload()
        await settle()
        logic.actions.loadOlder()
        await settle()

        expect(turnIds()).toEqual(['trace-0', 'trace-1', 'trace-2'])
        expect(router.values.searchParams).toMatchObject({ trace: 'trace-1' })
    })
})
