import { waitFor } from '@testing-library/react'
import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import type { ErrorGroupDetailApi, TracePageRequestApi } from '../../generated/api.schemas'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { traceDrawerLogic } from '../trace/traceDrawerLogic'
import { TRACE_CELL_URLS, makeTraceListPage, makeTracePreview } from '../traces/testFixtures'
import { errorDrawerLogic } from './errorDrawerLogic'
import {
    ERRORS_URL,
    ERROR_FIRST_SEEN_URL,
    makeErrorFirstSeen,
    makeErrorFirstSeenList,
    makeErrorListItem,
    makeErrorListPage,
} from './testFixtures'

const LIST_PATH = urls.aiObservabilityErrors()
const DETAIL_URL = '/api/projects/:team_id/ai_observability/errors/:key/'
const TRACES_URL = '/api/projects/:team_id/ai_observability/traces/'
const MESSAGE = 'TimeoutError: the café model took longer than 30s?'
// The server's encode_entity_key of MESSAGE: unpadded base64url of its UTF-8 bytes.
const MESSAGE_KEY = 'VGltZW91dEVycm9yOiB0aGUgY2Fmw6kgbW9kZWwgdG9vayBsb25nZXIgdGhhbiAzMHM_'
const FILTERS = [
    { key: '$ai_model', value: ['example-model'], operator: PropertyOperator.Exact, type: PropertyFilterType.Event },
]
const SELECTION = {
    date_from: '-30d',
    filter_test_accounts: 'true',
    properties: JSON.stringify(FILTERS),
}
const LIST_URL = combineUrl(LIST_PATH, {
    date_from: '-30d',
    filter_test_accounts: 'true',
    filters: FILTERS,
    error_search: 'timeout',
}).url

const NARROWER_RANGE = '-14d'

type DrawerRead = 'detail' | 'recent_traces' | 'first_seen'
const FIRST_SEEN_PARAMS = { date_from: '-30d', filter_test_accounts: 'true' }

function makeDetail(message: string, occurrences: number): ErrorGroupDetailApi {
    return {
        item: makeErrorListItem({ key: MESSAGE_KEY, message, occurrences }),
        bucketStarts: ['2026-09-01T00:00:00Z', '2026-09-02T00:00:00Z'],
        previousSeries: [3, 4],
    }
}

describe('errorDrawerLogic', () => {
    let detailRequests: { key: string; params: Record<string, string> }[]
    let traceRequests: Record<string, string>[]
    let pageKeys: string[]
    let firstSeenReads: { params: Record<string, string>; keys: string[] }[]
    let pageHeld: Promise<void> | null
    let failing: { read: DrawerRead; status: number } | null
    let held: Promise<void> | null
    let capture: jest.SpyInstance
    let logic: ReturnType<typeof errorDrawerLogic.build>

    const param = (name: string): string | null => new URLSearchParams(router.values.location.search).get(name)
    const captured = (event: string): unknown[] =>
        capture.mock.calls.filter(([name]) => name === event).map(([, properties]) => properties)

    async function mountAt(url: string): Promise<void> {
        router.actions.push(url)
        logic = errorDrawerLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        localStorage.clear()
        detailRequests = []
        traceRequests = []
        pageKeys = ['error-a', 'error-b']
        firstSeenReads = []
        pageHeld = null
        failing = null
        held = null
        useMocks({
            get: {
                [DETAIL_URL]: async ({ request, params }) => {
                    const searchParams = new URL(request.url).searchParams
                    detailRequests.push({ key: String(params.key), params: Object.fromEntries(searchParams) })
                    await held
                    if (failing?.read === 'detail') {
                        return [failing.status, { detail: 'failed' }]
                    }
                    const narrower = searchParams.get('date_from') === NARROWER_RANGE
                    return [200, makeDetail(MESSAGE, narrower ? 320 : 640)]
                },
                [ERRORS_URL]: async () => {
                    await pageHeld
                    return [200, makeErrorListPage(pageKeys)]
                },
                [TRACES_URL]: async ({ request }) => {
                    const searchParams = new URL(request.url).searchParams
                    traceRequests.push(Object.fromEntries(searchParams))
                    await held
                    if (failing?.read === 'recent_traces') {
                        return [failing.status, { detail: 'failed' }]
                    }
                    const narrower = searchParams.get('date_from') === NARROWER_RANGE
                    return [200, makeTraceListPage(narrower ? ['trace-3'] : ['trace-1', 'trace-2'])]
                },
            },
            post: {
                [ERROR_FIRST_SEEN_URL]: async ({ request }: { request: Request }) => {
                    const { keys }: { keys: string[] } = await request.json()
                    firstSeenReads.push({ params: Object.fromEntries(new URL(request.url).searchParams), keys })
                    if (failing?.read === 'first_seen') {
                        return [failing.status, { detail: 'failed' }]
                    }
                    const items = keys.map((key) => makeErrorFirstSeen(key, { isNew: key === MESSAGE_KEY }))
                    return [200, makeErrorFirstSeenList(items)]
                },
                [TRACE_CELL_URLS.previews]: async ({ request }: { request: Request }) => {
                    const body: TracePageRequestApi = await request.json()
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

    it('opens a row with its header at once, then reads the detail and the five recent traces of its selection', async () => {
        pageKeys = [MESSAGE_KEY]
        await mountAt(LIST_URL)
        const row = makeErrorListItem({ key: MESSAGE_KEY, message: MESSAGE, occurrences: 128 })

        logic.actions.openError(row)

        expect(param('error')).toEqual(MESSAGE_KEY)
        expect(logic.values.item).toEqual(row)
        await expectLogic(logic).toFinishAllListeners()
        expect(detailRequests).toEqual([{ key: MESSAGE_KEY, params: SELECTION }])
        expect(traceRequests).toEqual([{ ...SELECTION, error: MESSAGE, limit: '5' }])
        expect(logic.values.item?.occurrences).toEqual(640)
        expect(logic.values.recentTraceRows.map((row) => row.traceId)).toEqual(['trace-1', 'trace-2'])
        expect(logic.values.previews.get('trace-1')).toEqual({ status: 'ready', value: makeTracePreview('trace-1') })
        expect(captured('llma diagnostics entity opened')).toEqual([{ kind: 'error', trigger: 'row' }])
        expect(logic.values.isNew).toBe(true)
        expect(firstSeenReads).toEqual([{ params: FIRST_SEEN_PARAMS, keys: [MESSAGE_KEY] }])
    })

    it('reads the detail of an error a direct link opens, and its first seen for New when it is off the page', async () => {
        await mountAt(combineUrl(LIST_URL, { error: MESSAGE_KEY }).url)

        expect(detailRequests.map(({ key }) => key)).toEqual([MESSAGE_KEY])
        expect(logic.values).toMatchObject({
            openMessage: MESSAGE,
            item: { message: MESSAGE, occurrences: 640 },
            detailLoad: { status: 'ready' },
            isNew: true,
        })
        expect(firstSeenReads).toHaveLength(2)
        expect(firstSeenReads).toEqual(
            expect.arrayContaining([
                { params: FIRST_SEEN_PARAMS, keys: [MESSAGE_KEY] },
                { params: FIRST_SEEN_PARAMS, keys: ['error-a', 'error-b'] },
            ])
        )
        expect(captured('llma diagnostics entity opened')).toEqual([{ kind: 'error', trigger: 'url' }])
    })

    it('asks first seen once for a direct link to an error on the page, before the page lands', async () => {
        pageKeys = [MESSAGE_KEY, 'error-b']
        let releasePage = (): void => {}
        pageHeld = new Promise((resolve) => {
            releasePage = resolve
        })
        router.actions.push(combineUrl(LIST_URL, { error: MESSAGE_KEY }).url)
        logic = errorDrawerLogic()
        logic.mount()
        await waitFor(() => expect(firstSeenReads).toHaveLength(1))

        releasePage()
        await expectLogic(logic).toFinishAllListeners()

        expect(firstSeenReads.map(({ keys }) => keys)).toEqual([[MESSAGE_KEY], ['error-b']])
        expect(logic.values.isNew).toBe(true)
    })

    it('shows no New when the first seen of an error off the page fails, and tracks the failure', async () => {
        failing = { read: 'first_seen', status: 500 }

        await mountAt(combineUrl(LIST_URL, { error: MESSAGE_KEY }).url)

        expect(logic.values).toMatchObject({ isNew: false, detailLoad: { status: 'ready' } })
        expect(logic.values.firstSeen.get(MESSAGE_KEY)).toEqual({ status: 'error' })
        expect(captured('llma diagnostics read failed')).toEqual(
            expect.arrayContaining([{ kind: 'error', read: 'first_seen' }])
        )
    })

    it('keeps the error open and unread again when the trace drawer over it opens and closes', async () => {
        await mountAt(combineUrl(LIST_URL, { error: MESSAGE_KEY }).url)
        const traceDrawer = traceDrawerLogic({ listId: 'error-traces' })
        traceDrawer.mount()

        traceDrawer.actions.setRows(logic.values.recentTraceRows)
        traceDrawer.actions.openRow(logic.values.recentTraceRows[1])
        expect(param('trace')).toEqual('trace-2')
        traceDrawer.actions.close()
        await expectLogic(logic).toFinishAllListeners()

        expect(param('trace')).toBeNull()
        expect(param('error')).toEqual(MESSAGE_KEY)
        expect(detailRequests).toHaveLength(1)
        expect(traceRequests).toHaveLength(1)
        traceDrawer.unmount()
    })

    it('closes a trace open over one error when another error opens', async () => {
        await mountAt(
            combineUrl(LIST_URL, { error: MESSAGE_KEY, trace: 'trace-1', ts: '2026-09-01', step: 'step-1' }).url
        )
        const other = makeErrorListItem({ key: 'T3RoZXI', message: 'Other' })

        logic.actions.openError(other)

        expect([param('error'), param('trace'), param('ts'), param('step')]).toEqual(['T3RoZXI', null, null, null])
    })

    it('drops only its own param when it closes', async () => {
        await mountAt(combineUrl(LIST_URL, { error: MESSAGE_KEY }).url)

        logic.actions.close()

        expect(param('error')).toBeNull()
        expect(param('error_search')).toEqual('timeout')
        expect(logic.values.openKey).toBeNull()
    })

    it('links to every trace with the error in the same selection, without the list view or any search', async () => {
        await mountAt(
            combineUrl(LIST_URL, { error: MESSAGE_KEY, view: 'increasing', order: 'users', trace_search: 'refund' }).url
        )

        const { pathname, searchParams } = combineUrl(logic.values.viewAllHref ?? '')

        expect(pathname).toEqual(urls.aiObservabilityTraces())
        expect(searchParams).toEqual({
            date_from: '-30d',
            filter_test_accounts: true,
            filters: FILTERS,
            error: MESSAGE,
        })
    })

    it('reads again when the range changes, showing loading rather than the values of the range before', async () => {
        await mountAt(combineUrl(LIST_URL, { error: MESSAGE_KEY }).url)
        let release = (): void => {}
        held = new Promise((resolve) => {
            release = resolve
        })

        shellScopeLogic.actions.setDateRange(NARROWER_RANGE, null)
        await expectLogic(logic).toDispatchActions(['loadErrorDetail', 'loadErrorRecentTraces'])

        expect(logic.values).toMatchObject({
            item: null,
            detailLoad: { status: 'loading' },
            recentTracesLoad: { status: 'loading' },
            recentTraceRows: [],
        })
        release()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.item?.occurrences).toEqual(320)
        expect(logic.values.recentTraceRows.map((row) => row.traceId)).toEqual(['trace-3'])
    })

    it('shows an error with no occurrences in the range as not found, which is no failure and no retry', async () => {
        silenceKeaLoadersErrors()
        failing = { read: 'detail', status: 404 }
        await mountAt(combineUrl(LIST_URL, { error: MESSAGE_KEY }).url)

        expect(logic.values).toMatchObject({
            item: null,
            detailLoad: { status: 'not_found' },
            recentTracesLoad: { status: 'ready', value: [] },
        })
        expect(traceRequests).toEqual([])
        expect(captured('llma diagnostics read failed')).toEqual([])
        await expectLogic(logic, () => logic.actions.retry()).toFinishAllListeners()
        expect(detailRequests).toHaveLength(1)
    })

    it.each([
        ['detail', 'detailLoad'],
        ['recent_traces', 'recentTracesLoad'],
    ] as const)(
        'shows a failed %s read as failed, reports it, and reads only it again on retry',
        async (read, loadKey) => {
            silenceKeaLoadersErrors()
            failing = { read, status: 500 }
            await mountAt(combineUrl(LIST_URL, { error: MESSAGE_KEY }).url)

            expect(logic.values[loadKey]).toEqual({ status: 'error' })
            expect(captured('llma diagnostics read failed')).toEqual([{ kind: 'error', read }])

            failing = null
            await expectLogic(logic, () => logic.actions.retry()).toFinishAllListeners()

            expect(logic.values[loadKey]).toMatchObject({ status: 'ready' })
            expect({ detail: detailRequests.length, recent_traces: traceRequests.length }).toEqual({
                detail: read === 'detail' ? 2 : 1,
                recent_traces: read === 'recent_traces' ? 2 : 1,
            })
        }
    )
})
