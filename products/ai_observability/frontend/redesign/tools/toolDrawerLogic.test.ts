import { waitFor } from '@testing-library/react'
import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TracePageRequestApi, ToolListItemApi } from '../../generated/api.schemas'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { TRACE_CELL_URLS, makeTraceListPage, makeTracePreview } from '../traces/testFixtures'
import { TOOL_DETAIL_URL, makeToolDetail, makeToolListItem } from './testFixtures'
import { toolDrawerLogic } from './toolDrawerLogic'

const LIST_PATH = urls.aiObservabilityTools()
const TRACES_URL = '/api/projects/:team_id/ai_observability/traces/'
const NAME = 'lookup/order café'
// The server's encode_entity_key of NAME: unpadded base64url of its UTF-8 bytes.
const NAME_KEY = 'bG9va3VwL29yZGVyIGNhZsOp'
const SELECTION = { date_from: '-30d', filter_test_accounts: 'true' }
const LIST_URL = combineUrl(LIST_PATH, { ...SELECTION, tool_search: 'lookup' }).url
const NARROWER_RANGE = '-14d'

type DrawerRead = 'detail' | 'failures' | 'calls'

describe('toolDrawerLogic', () => {
    let reads: { read: DrawerRead; key?: string; params: Record<string, string> }[]
    let failing: { read: DrawerRead; status: number } | null
    let detailFailures: number | null
    let held: Promise<void> | null
    let callTraces: string[]
    let previewsHeld: Promise<void> | null
    let previewReads: string[][]
    let capture: jest.SpyInstance
    let logic: ReturnType<typeof toolDrawerLogic.build>

    const param = (name: string): string | null => new URLSearchParams(router.values.location.search).get(name)
    const readsOf = (read: DrawerRead): Record<string, string>[] =>
        reads.filter((entry) => entry.read === read).map((entry) => entry.params)
    const captured = (event: string): unknown[] =>
        capture.mock.calls.filter(([name]) => name === event).map(([, properties]) => properties)
    const row = (overrides: Partial<ToolListItemApi> = {}): ToolListItemApi =>
        makeToolListItem({ key: NAME_KEY, name: NAME, ...overrides })

    async function mountAt(url: string): Promise<void> {
        router.actions.push(url)
        logic = toolDrawerLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        localStorage.clear()
        reads = []
        failing = null
        detailFailures = 12
        held = null
        callTraces = ['call-1', 'call-2']
        previewsHeld = null
        previewReads = []
        useMocks({
            get: {
                [TOOL_DETAIL_URL]: async ({ request, params }) => {
                    const searchParams = new URL(request.url).searchParams
                    reads.push({ read: 'detail', key: String(params.key), params: Object.fromEntries(searchParams) })
                    await held
                    if (failing?.read === 'detail') {
                        return [failing.status, { detail: 'failed' }]
                    }
                    const narrower = searchParams.get('date_from') === NARROWER_RANGE
                    return [
                        200,
                        makeToolDetail({
                            key: NAME_KEY,
                            name: NAME,
                            calls: narrower ? 300 : 900,
                            failures: detailFailures,
                        }),
                    ]
                },
                [TRACES_URL]: async ({ request }) => {
                    const searchParams = new URL(request.url).searchParams
                    const read: DrawerRead = searchParams.has('failed_tool') ? 'failures' : 'calls'
                    reads.push({ read, params: Object.fromEntries(searchParams) })
                    await held
                    if (failing?.read === read) {
                        return [failing.status, { detail: 'failed' }]
                    }
                    return [200, makeTraceListPage(read === 'failures' ? ['failed-1'] : callTraces)]
                },
            },
            post: {
                [TRACE_CELL_URLS.previews]: async ({ request }: { request: Request }) => {
                    const body: TracePageRequestApi = await request.json()
                    previewReads.push(body.trace_ids)
                    await previewsHeld
                    return [200, { items: body.trace_ids.map((id) => makeTracePreview(id)) }]
                },
            },
        })
        initKeaTests()
        capture = jest.spyOn(posthog, 'capture')
    })

    afterEach(() => {
        logic.unmount()
        resumeKeaLoadersErrors()
        jest.restoreAllMocks()
    })

    it('opens a row at once, then reads its detail, five recent failures and five recent calls', async () => {
        await mountAt(LIST_URL)
        const opened = row({ calls: 120 })

        logic.actions.openTool(opened)

        expect(param('tool')).toEqual(NAME_KEY)
        expect(logic.values.item).toEqual(opened)
        await expectLogic(logic).toFinishAllListeners()
        expect(readsOf('detail')).toEqual([SELECTION])
        expect(reads.find((entry) => entry.read === 'detail')?.key).toEqual(NAME_KEY)
        expect(readsOf('failures')).toEqual([{ ...SELECTION, failed_tool: NAME, limit: '5' }])
        expect(readsOf('calls')).toEqual([{ ...SELECTION, tool: NAME, limit: '5' }])
        expect(logic.values).toMatchObject({
            item: { calls: 900 },
            showsFailures: true,
            recentFailuresLoad: { status: 'ready' },
            recentCallsLoad: { status: 'ready' },
        })
        expect(logic.values.previews.get('failed-1')).toEqual({ status: 'ready', value: makeTracePreview('failed-1') })
        expect(captured('llma diagnostics entity opened')).toEqual([{ kind: 'tool', trigger: 'row' }])
    })

    it.each([
        ['no result was captured', null],
        ['no captured result failed', 0],
    ])('hides recent failures and makes no failed_tool read when %s', async (_name, failures) => {
        detailFailures = failures
        await mountAt(LIST_URL)

        logic.actions.openTool(row({ failures, failureRate: failures, failureState: 'not_captured' }))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.showsFailures).toBe(false)
        expect(readsOf('failures')).toEqual([])
        expect(readsOf('calls')).toHaveLength(1)
    })

    it('reads the recent failures of a tool a direct link opens once its detail shows failures', async () => {
        await mountAt(combineUrl(LIST_URL, { tool: NAME_KEY }).url)

        expect(logic.values).toMatchObject({ openName: NAME, showsFailures: true, detailLoad: { status: 'ready' } })
        expect(reads.map(({ read }) => read).sort()).toEqual(['calls', 'detail', 'failures'])
        expect(captured('llma diagnostics entity opened')).toEqual([{ kind: 'tool', trigger: 'url' }])
    })

    it('steps through the traces of the section a trace opened from', async () => {
        await mountAt(combineUrl(LIST_URL, { tool: NAME_KEY }).url)
        expect(logic.values.traceRows.map((traceRow) => traceRow.traceId)).toEqual(['call-1', 'call-2'])

        logic.actions.setTraceSection('failures')

        expect(logic.values.traceRows.map((traceRow) => traceRow.traceId)).toEqual(['failed-1'])
        expect(param('trace_section')).toEqual('failures')
    })

    it('keeps the section of an open trace in the URL, so a refresh steps through the same traces', async () => {
        await mountAt(combineUrl(LIST_URL, { tool: NAME_KEY, trace_section: 'failures', trace: 'failed-1' }).url)

        expect(logic.values.traceSection).toEqual('failures')
        expect(logic.values.traceRows.map((traceRow) => traceRow.traceId)).toEqual(['failed-1'])
    })

    it.each(['../../../../users/@me', 'a/b', 'key=='])(
        'reads nothing for a tool param the server never hands out: %s',
        async (value) => {
            await mountAt(combineUrl(LIST_URL, { tool: value }).url)

            expect(logic.values.openKey).toBeNull()
            expect(readsOf('detail')).toEqual([])
        }
    )

    it('reads a preview once for a trace both sections show while its first read is in flight', async () => {
        callTraces = ['failed-1', 'call-1']
        let release = (): void => {}
        previewsHeld = new Promise((resolve) => {
            release = resolve
        })
        router.actions.push(combineUrl(LIST_URL, { tool: NAME_KEY }).url)
        logic = toolDrawerLogic()
        logic.mount()
        await waitFor(() => expect(previewReads).toHaveLength(2))

        release()
        await expectLogic(logic).toFinishAllListeners()

        expect(previewReads.flat().sort()).toEqual(['call-1', 'failed-1'])
        expect(logic.values.previews.get('failed-1')).toEqual({ status: 'ready', value: makeTracePreview('failed-1') })
    })

    it('reads again when the range changes, showing loading rather than the values of the range before', async () => {
        await mountAt(combineUrl(LIST_URL, { tool: NAME_KEY }).url)
        let release = (): void => {}
        held = new Promise((resolve) => {
            release = resolve
        })

        shellScopeLogic.actions.setDateRange(NARROWER_RANGE, null)
        await expectLogic(logic).toDispatchActions(['loadToolDetail', 'loadToolRecentCalls'])

        expect(logic.values).toMatchObject({
            item: null,
            detailLoad: { status: 'loading' },
            recentFailuresLoad: { status: 'loading' },
            recentCallsLoad: { status: 'loading' },
            traceRows: [],
        })
        release()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.item?.calls).toEqual(300)
    })

    it('closes a trace open over one tool when another tool opens', async () => {
        await mountAt(combineUrl(LIST_URL, { tool: NAME_KEY, trace: 'call-1', ts: '2026-09-01', step: 'step-1' }).url)

        logic.actions.openTool(makeToolListItem({ key: 'b3RoZXI', name: 'other' }))

        expect([param('tool'), param('trace'), param('ts'), param('step')]).toEqual(['b3RoZXI', null, null, null])
    })

    it('links to every trace that called the tool in the same selection, without the list view or any search', async () => {
        await mountAt(combineUrl(LIST_URL, { tool: NAME_KEY, view: 'failing', trace_search: 'refund' }).url)

        const { pathname, searchParams } = combineUrl(logic.values.viewAllHref ?? '')

        expect(pathname).toEqual(urls.aiObservabilityTraces())
        expect(searchParams).toEqual({ date_from: '-30d', filter_test_accounts: true, tool: NAME })
    })

    it('shows a tool with no calls in the range as not found, which is no failure and no retry', async () => {
        silenceKeaLoadersErrors()
        failing = { read: 'detail', status: 404 }
        await mountAt(combineUrl(LIST_URL, { tool: NAME_KEY }).url)

        expect(logic.values).toMatchObject({
            item: null,
            detailLoad: { status: 'not_found' },
            recentCallsLoad: { status: 'ready', value: [] },
        })
        expect(readsOf('calls')).toEqual([])
        expect(captured('llma diagnostics read failed')).toEqual([])
        await expectLogic(logic, () => logic.actions.retry()).toFinishAllListeners()
        expect(readsOf('detail')).toHaveLength(1)
    })

    it.each([
        ['detail', 'detailLoad', 'detail'],
        ['failures', 'recentFailuresLoad', 'recent_traces'],
        ['calls', 'recentCallsLoad', 'recent_traces'],
    ] as const)(
        'shows a failed %s read, reports it, and reads only it again on retry',
        async (read, loadKey, tracked) => {
            silenceKeaLoadersErrors()
            await mountAt(LIST_URL)
            failing = { read, status: 500 }
            logic.actions.openTool(row())
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values[loadKey]).toEqual({ status: 'error' })
            expect(captured('llma diagnostics read failed')).toEqual([{ kind: 'tool', read: tracked }])

            failing = null
            await expectLogic(logic, () => logic.actions.retry()).toFinishAllListeners()

            expect(logic.values[loadKey]).toMatchObject({ status: 'ready' })
            expect(readsOf(read)).toHaveLength(2)
            expect(reads).toHaveLength(4)
        }
    )
})
