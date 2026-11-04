import { combineUrl, decodeParams, router } from 'kea-router'
import { getRouterContext } from 'kea-router/lib/router'
import posthog from 'posthog-js'

import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { addProductIntent } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import type { TraceDrawerListId } from './traceDrawerLists'
import { traceDrawerLogic } from './traceDrawerLogic'
import { withoutTraceDrawerParams } from './traceDrawerRows'
import { TraceListRow } from './traceListRows'
import { traceViewHostLogic } from './traceViewHostLogic'

jest.mock('lib/utils/product-intents', () => ({
    ...jest.requireActual('lib/utils/product-intents'),
    addProductIntent: jest.fn(),
}))

const FLAG = FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN
const LIST_PATH = urls.aiObservabilityTraces()

const A: TraceListRow = { traceId: 'a', timestamp: null, stepId: 'x' }
const A2: TraceListRow = { traceId: 'a', timestamp: null, stepId: 'y' }
const B: TraceListRow = { traceId: 'b', timestamp: null, stepId: null }
const C: TraceListRow = { traceId: 'c', timestamp: '2026-01-01T12:00:00+00:00', stepId: 'z' }

describe('traceDrawerLogic', () => {
    let logic: ReturnType<typeof traceDrawerLogic.build>
    let host: ReturnType<typeof traceViewHostLogic.build>
    let browserHistory: string[]
    let capture: jest.SpyInstance

    const param = (name: string): string | null => new URLSearchParams(router.values.location.search).get(name)
    const capturedEvents = (): unknown[][] =>
        capture.mock.calls.filter(([event]) => String(event).startsWith('llma trace drawer'))

    // Back and forward decode the URL again, as a page load does.
    function goTo(url: string): void {
        const { pathname, search, hash } = new URL(url, 'https://example.com')
        router.actions.locationChanged({
            method: 'POP',
            pathname,
            search,
            searchParams: decodeParams(search, '?'),
            hash,
            hashParams: decodeParams(hash, '#'),
            url,
        })
    }

    function routerHistory(): NonNullable<ReturnType<typeof getRouterContext>['history']> {
        const { history } = getRouterContext()
        if (!history) {
            throw new Error('The router has no history in this test')
        }
        return history
    }

    function goBack(): void {
        browserHistory.pop()
        goTo(browserHistory[browserHistory.length - 1])
    }

    function mountDrawer(listId: TraceDrawerListId = 'traces'): void {
        logic = traceDrawerLogic({ listId })
        logic.mount()
        host = traceViewHostLogic({ hostId: logic.values.hostId })
        host.mount()
    }

    function setUp({
        url = LIST_PATH,
        flag = true,
        listId,
    }: { url?: string; flag?: boolean; listId?: TraceDrawerListId } = {}): void {
        initKeaTests()
        localStorage.clear()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FLAG], { [FLAG]: flag })
        goTo(url)

        browserHistory = [url]
        routerHistory().pushState = (_state: unknown, _title: string, target: string): void => {
            browserHistory.push(target)
        }
        routerHistory().replaceState = (_state: unknown, _title: string, target: string): void => {
            browserHistory[browserHistory.length - 1] = target
        }

        capture = jest.spyOn(posthog, 'capture')
        mountDrawer(listId)
    }

    afterEach(() => {
        if (logic.isMounted()) {
            logic.unmount()
        }
        jest.restoreAllMocks()
        jest.mocked(addProductIntent).mockClear()
        document.body.innerHTML = ''
    })

    it('steps by trace, so a repeated trace cannot trap next', () => {
        setUp()
        logic.actions.setRows([A, A2, B])
        logic.actions.openRow(A)
        expect(logic.values.position).toEqual({ index: 0, total: 2 })

        logic.actions.stepTo('next')

        expect(logic.values.openTraceId).toBe('b')
        expect(logic.values.previousTrace).toEqual(A)
        expect(logic.values.nextTrace).toBeNull()
    })

    it('does not revisit a repeat below a trace it passed', () => {
        setUp()
        logic.actions.setRows([A, B, A2])
        logic.actions.openRow(B)

        expect(logic.values.position).toEqual({ index: 1, total: 2 })
        expect(logic.values.nextTrace).toBeNull()
    })

    it('stays open with no position when the open trace leaves the rows', () => {
        setUp()
        logic.actions.setRows([A, B])
        logic.actions.openRow(A)

        logic.actions.setRows([B])

        expect(logic.values.openTraceId).toBe('a')
        expect(logic.values).toMatchObject({ position: null, previousTrace: null, nextTrace: null })
    })

    it('does nothing when stepping past either end', () => {
        setUp()
        logic.actions.setRows([A])
        logic.actions.openRow(A)
        const entries = browserHistory.length

        logic.actions.stepTo('next')
        logic.actions.stepTo('previous')

        expect(browserHistory).toHaveLength(entries)
        expect(capturedEvents().filter(([event]) => event === 'llma trace drawer stepped')).toEqual([])
    })

    it('replaces the step for another row of the open trace and writes nothing for the row on show', () => {
        setUp()
        logic.actions.setRows([A, A2, B])
        logic.actions.openRow(A)
        const entries = browserHistory.length

        logic.actions.openRow(A2)
        expect(param('step')).toBe('y')
        expect(logic.values.position).toEqual({ index: 0, total: 2 })
        expect(browserHistory).toHaveLength(entries)

        const url = browserHistory[browserHistory.length - 1]
        logic.actions.openRow(A2)
        expect(browserHistory[browserHistory.length - 1]).toBe(url)
    })

    it('keeps the selected step when a row with no step targets the open trace', () => {
        setUp()
        logic.actions.openRow(A)
        host.actions.requestStep('y', 'a')
        const url = browserHistory[browserHistory.length - 1]

        logic.actions.openRow({ ...A, stepId: null })

        expect(host.values.requestedStepId).toBe('y')
        expect(browserHistory[browserHistory.length - 1]).toBe(url)
    })

    it('carries the mode and step tab between traces, and resets them when reopened', () => {
        setUp()
        logic.actions.setRows([A, B, C])
        logic.actions.openRow(A)
        host.actions.setMode('thread')
        host.actions.setDetailTab('raw')

        logic.actions.stepTo('next')
        logic.actions.openRow(C)
        expect(host.values).toMatchObject({ mode: 'thread', detailTab: 'raw' })

        logic.actions.close()
        logic.actions.openRow(A)
        expect(host.values).toMatchObject({ mode: 'spans', detailTab: 'messages' })
    })

    it.each<[TraceDrawerListId, string, Record<string, unknown>]>([
        ['traces', LIST_PATH, { mode: 'spans', detailTab: 'messages', openingMode: null }],
        [
            'evaluation-runs',
            urls.aiObservabilityEvaluation('e1'),
            { mode: 'spans', detailTab: 'evals', openingMode: null },
        ],
        [
            'cluster-traces',
            urls.aiObservabilityCluster('run-1', 3),
            { mode: 'spans', detailTab: 'messages', openingMode: 'summary' },
        ],
    ])('opens %s with its own opening, and keeps what the person changed when stepping', (listId, url, opening) => {
        setUp({ url, listId })
        host.actions.setMode('thread')
        host.actions.setDetailTab('raw')
        logic.actions.setRows([A, B])

        logic.actions.openRow(A)
        expect(host.values).toMatchObject(opening)

        host.actions.setMode('thread')
        host.actions.setDetailTab('raw')
        logic.actions.stepTo('next')
        expect(host.values).toMatchObject({ mode: 'thread', detailTab: 'raw', openingMode: null })
    })

    it('goes back through each trace it stepped through, and back to the list', () => {
        setUp()
        logic.actions.setRows([A, B, C])
        logic.actions.openRow(A)
        logic.actions.stepTo('next')
        host.actions.requestStep('b-step', 'b')
        logic.actions.stepTo('next')

        goBack()
        expect(logic.values.openRef).toEqual({ ...B, stepId: 'b-step' })
        expect(host.values.requestedStepId).toBe('b-step')

        goBack()
        expect(logic.values.openRef).toEqual(A)

        goBack()
        expect(logic.values.openRef).toBeNull()
    })

    it.each(['a/b#c', '123', '1.50', 'true', '[draft]', '{"a":1}'])('round-trips the trace id %s', (traceId) => {
        setUp()
        const row = { traceId, timestamp: '2026-01-01T12:00:00+00:00', stepId: traceId }

        logic.actions.openRow(row)
        expect(logic.values.openRef).toEqual(row)

        goTo(browserHistory[browserHistory.length - 1])
        expect(logic.values.openRef).toEqual(row)
    })

    it('reads a link with a numeric trace as text', () => {
        setUp({ url: `${LIST_PATH}?trace=1.50&ts=2026&step=2.0` })

        expect(logic.values.openRef).toEqual({ traceId: '1.50', timestamp: '2026', stepId: '2.0' })
    })

    it('keeps a numeric trace and step as text when another logic rewrites the URL', () => {
        setUp({ url: `${LIST_PATH}?date_from=-7d&trace=1.50&ts=2026&step=2.0` })

        router.actions.replace(router.values.location.pathname, { ...router.values.searchParams, date_from: '-1d' })

        expect(logic.values.openRef).toEqual({ traceId: '1.50', timestamp: '2026', stepId: '2.0' })
        expect(param('date_from')).toBe('-1d')
        expect(browserHistory).toHaveLength(1)
    })

    it.each([
        ['steps', ['01', '1'], (): void => logic.actions.stepTo('next'), '1'],
        [
            'goes back',
            ['1', '01'],
            (): void => {
                logic.actions.stepTo('next')
                goBack()
            },
            '1',
        ],
    ])('%s between distinct numeric-looking traces', (_name, traceIds, navigate, expected) => {
        setUp({ url: `${LIST_PATH}?trace=${traceIds[0]}` })
        logic.actions.setRows(traceIds.map((traceId) => ({ traceId, timestamp: null, stepId: null })))

        navigate()

        expect(logic.values.openTraceId).toBe(expected)
    })

    it('treats an empty trace param as closed', () => {
        setUp({ url: `${LIST_PATH}?trace=` })

        expect(logic.values.openRef).toBeNull()
    })

    it.each([
        ['opening', (): void => logic.actions.openRow(B)],
        ['stepping', (): void => logic.actions.stepTo('next')],
        ['a requested step', (): void => host.actions.requestStep('gen-2', '1.50')],
        ['closing', (): void => logic.actions.close()],
    ])('keeps the other params and the hash when %s', (_name, write) => {
        setUp({
            url: `${LIST_PATH}?trace_search=1.50&review_search=007&on=TRUE&filters=[{"a":1}]&date_from=-7d&trace=1.50&ts=2.50&step=3.50#panel=discussion`,
        })
        logic.actions.setRows([{ traceId: '1.50', timestamp: '2.50', stepId: '3.50' }, B])

        write()

        expect(param('trace_search')).toBe('1.50')
        expect(param('review_search')).toBe('007')
        expect(param('on')).toBe('TRUE')
        expect(router.values.searchParams.filters).toEqual([{ a: 1 }])
        expect(param('date_from')).toBe('-7d')
        expect(router.values.hashParams).toEqual({ panel: 'discussion' })
    })

    it.each(['1.50', '{"a": 1}'])('keeps the raw open trace %s when a step is written', (traceId) => {
        setUp({ url: combineUrl(LIST_PATH, { trace: traceId, ts: '2.50' }).url })

        host.actions.requestStep('gen-2', traceId)

        expect(logic.values.openRef).toEqual({ traceId, timestamp: '2.50', stepId: 'gen-2' })
        expect(browserHistory).toHaveLength(1)
    })

    it('does not write a step the URL already holds', () => {
        setUp({ url: `${LIST_PATH}?trace=a&step=1.50` })
        const replaceState = jest.spyOn(routerHistory(), 'replaceState')

        host.actions.requestStep('1.50', 'a')

        expect(replaceState).not.toHaveBeenCalled()
    })

    it('leaves the list URL alone for a step requested while closed', () => {
        setUp()

        host.actions.requestStep('gen-2', 'a')

        expect(param('step')).toBeNull()
    })

    it('hands the host the step before the new trace renders', () => {
        setUp()
        logic.actions.setRows([A, B])

        logic.actions.openRow(A)
        expect(host.values).toMatchObject({ requestedStepId: 'x', requestedTraceId: 'a' })

        logic.actions.stepTo('next')
        expect(host.values).toMatchObject({ requestedStepId: null, requestedTraceId: 'b' })
    })

    it('sends a link to the trace page, without tracking, when the flag is off', () => {
        setUp({ flag: false })
        logic.unmount()
        goTo(`${LIST_PATH}?date_from=-7d&trace=a%2Fb&ts=2026-01-01&step=gen-1`)

        mountDrawer()

        expect(logic.values.isEnabled).toBe(false)
        expect(router.values.location.pathname).toContain(urls.aiObservabilityTrace('a/b'))
        expect(router.values.searchParams).toEqual({
            date_from: '-7d',
            timestamp: '2026-01-01',
            event: 'gen-1',
            back_to: 'traces',
            back_url: `${LIST_PATH}?date_from=-7d`,
        })
        expect(capturedEvents()).toEqual([])
        expect(addProductIntent).not.toHaveBeenCalled()
    })

    it('sends a trace-level link to the trace page with no event, because that page is the legacy scene', () => {
        const path = urls.aiObservabilityEvaluation('e1')

        setUp({ url: `${path}?trace=a`, flag: false, listId: 'evaluation-runs' })

        expect(router.values.location.pathname).toContain(urls.aiObservabilityTrace('a'))
        expect(router.values.searchParams).toEqual({ tab: 'evals', back_to: 'evaluation', back_url: path })
    })

    it('keeps its params on unmount, so a list that remounts while it loads reopens the trace', () => {
        setUp({ url: `${LIST_PATH}?trace_search=1.50&trace=a&ts=2026&step=x` })
        logic.actions.setRows([A, B])
        logic.actions.stepTo('next')
        const search = router.values.location.search

        host.unmount()
        logic.unmount()

        expect(router.values.location.search).toBe(search)
        expect(capturedEvents()).toContainEqual(['llma trace drawer closed', { steps: 1 }])

        mountDrawer()
        expect(logic.values.openTraceId).toBe(B.traceId)
    })

    it('stays open when the browser goes back to a list with an open drawer', () => {
        const openSearch = '?date_from=-7d&trace=a&ts=2026&step=x'
        setUp({ url: urls.aiObservabilityGenerations(), listId: 'generations' })

        goTo(`${LIST_PATH}${openSearch}`)
        const previousList = traceDrawerLogic({ listId: 'traces' })
        const unmountPreviousList = previousList.mount()
        logic.unmount()

        expect(previousList.values.openTraceId).toBe('a')
        expect(router.values.location.search).toBe(openSearch)
        expect(capturedEvents()).toEqual([['llma trace drawer opened', { list: 'traces' }]])
        unmountPreviousList()
    })

    it('leaves the next list closed when a tab link drops the drawer params', () => {
        setUp({ url: `${LIST_PATH}?date_from=-7d&trace=a&ts=2026&step=x` })

        router.actions.push(
            combineUrl(urls.aiObservabilityGenerations(), withoutTraceDrawerParams(router.values.searchParams)).url
        )
        const nextList = traceDrawerLogic({ listId: 'generations' })
        const unmountNextList = nextList.mount()
        logic.unmount()

        expect(nextList.values.openRef).toBeNull()
        expect(param('date_from')).toBe('-7d')
        expect(capturedEvents()).toEqual([
            ['llma trace drawer opened', { list: 'traces' }],
            ['llma trace drawer closed', { steps: 0 }],
        ])
        unmountNextList()
    })

    it.each<[TraceDrawerListId, string]>([
        ['traces', urls.aiObservabilityTraces()],
        ['generations', urls.aiObservabilityGenerations()],
        ['prompt-traces', urls.aiObservabilityPrompt('p1')],
        ['reviews', urls.aiObservabilityReviews()],
        ['review-queue', urls.aiObservabilityReviews()],
        ['evaluation-runs', urls.aiObservabilityEvaluation('e1')],
        ['evaluation-runs', `/project/1${urls.aiObservabilityEvaluation('e1')}`],
        ['dataset-items', urls.aiObservabilityDataset('d1')],
        ['cluster-traces', urls.aiObservabilityCluster('run:1', 3)],
    ])('opens %s at %s', (listId, path) => {
        setUp({ url: `${path}?trace=a`, listId })

        expect(logic.values.openTraceId).toBe('a')
    })

    it.each<[TraceDrawerListId, string]>([
        ['traces', urls.aiObservabilityTrace('a')],
        ['traces', urls.aiObservabilityGenerations()],
        ['prompt-traces', urls.aiObservabilityPrompts()],
        ['evaluation-runs', urls.aiObservabilityEvaluations()],
        ['evaluation-runs', urls.aiObservabilityEvaluationTemplates()],
        ['evaluation-runs', urls.aiObservabilityScorers()],
        ['evaluation-runs', '/ai-evals/evaluations/offline'],
        ['evaluation-runs', urls.aiObservabilityDataset('d1')],
        ['dataset-items', urls.aiObservabilityEvaluation('e1')],
        ['cluster-traces', urls.aiObservabilityClusters('run:1')],
    ])('leaves %s closed at %s', (listId, path) => {
        setUp({ url: `${path}?trace=a`, listId })

        expect(logic.values.openTraceId).toBeNull()
        expect(capturedEvents()).toEqual([])
    })

    it.each([
        ['enabled', true],
        ['disabled', false],
    ])('ignores a trace param on another product URL when %s', (_name, flag) => {
        setUp({ flag })
        const search = '?trace=0AF7651916CD43DD&ts=2026-01-01T00:00:00Z'
        const replaceState = jest.spyOn(routerHistory(), 'replaceState')

        goTo(`/tracing${search}`)
        expect(logic.values.openRef).toBeNull()
        logic.unmount()

        expect(router.values.location.pathname).toBe('/tracing')
        expect(router.values.location.search).toBe(search)
        expect(replaceState).not.toHaveBeenCalled()
        expect(capturedEvents()).toEqual([])
        expect(addProductIntent).not.toHaveBeenCalled()
    })

    it('leaves the URL alone on unmount when closed', () => {
        setUp({ url: `${LIST_PATH}?trace_search=1.50` })
        const replaceState = jest.spyOn(routerHistory(), 'replaceState')

        logic.unmount()

        expect(replaceState).not.toHaveBeenCalled()
    })

    it.each([
        ['the close control', (): void => logic.actions.close()],
        ['the back button', (): void => goTo(LIST_PATH)],
    ])('counts the steps in the closed event, and only since this open, through %s', (_name, leave) => {
        setUp()
        logic.actions.setRows([A, B, C])
        logic.actions.openRow(A)
        logic.actions.stepTo('next')
        logic.actions.stepTo('next')
        logic.actions.stepTo('previous')
        logic.actions.openRow(C)

        leave()
        logic.actions.openRow(A)
        logic.actions.close()

        expect(capturedEvents()).toEqual([
            ['llma trace drawer opened', { list: 'traces' }],
            ['llma trace drawer stepped', { direction: 'next' }],
            ['llma trace drawer stepped', { direction: 'next' }],
            ['llma trace drawer stepped', { direction: 'previous' }],
            ['llma trace drawer closed', { steps: 3 }],
            ['llma trace drawer opened', { list: 'traces' }],
            ['llma trace drawer closed', { steps: 0 }],
        ])
    })

    it('records one product intent and completes the setup tasks per open', () => {
        setUp()
        globalSetupLogic.mount()
        const markTaskAsCompleted = jest.spyOn(globalSetupLogic.actions, 'markTaskAsCompleted')
        logic.actions.setRows([A, B])
        logic.actions.openRow(A)
        logic.actions.stepTo('next')

        expect(addProductIntent).toHaveBeenCalledTimes(1)
        expect(addProductIntent).toHaveBeenCalledWith({
            product_type: ProductKey.AI_OBSERVABILITY,
            intent_context: ProductIntentContext.LLM_ANALYTICS_TRACE_VIEWED,
        })
        expect(markTaskAsCompleted).toHaveBeenCalledTimes(1)
        expect(markTaskAsCompleted).toHaveBeenCalledWith([SetupTaskId.IngestFirstLlmEvent, SetupTaskId.ViewFirstTrace])
    })

    it('tracks an open from a reload or a shared link', () => {
        setUp({ url: `${LIST_PATH}?trace=a` })

        expect(capturedEvents()).toEqual([['llma trace drawer opened', { list: 'traces' }]])
        expect(addProductIntent).toHaveBeenCalledTimes(1)
    })

    it('closes on Escape while open, and stops listening once closed', () => {
        setUp()
        logic.actions.setRows([A, B])
        logic.actions.openRow(A)
        logic.actions.stepTo('next')

        const entries = browserHistory.length

        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
        expect(logic.values.openRef).toBeNull()
        expect(browserHistory).toHaveLength(entries + 1)

        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
        expect(browserHistory).toHaveLength(entries + 1)
    })

    it('links to the full page with the selected step and the list params', () => {
        setUp({ url: `${LIST_PATH}?trace_search=1.50&date_from=-7d&trace=a%2Fb%23c&ts=2026-01-01&step=gen-1` })
        host.actions.requestStep('gen-2', 'a/b#c')

        const href = logic.values.fullPageHref ?? ''

        expect(href.split('?')[0]).toBe(urls.aiObservabilityTrace('a/b#c'))
        expect(Object.fromEntries(new URLSearchParams(href.split('?')[1]))).toEqual({
            trace_search: '1.50',
            date_from: '-7d',
            timestamp: '2026-01-01',
            event: 'gen-2',
            back_to: 'traces',
            back_url: `${LIST_PATH}?trace_search=1.50&date_from=-7d`,
        })
    })

    it.each<[TraceDrawerListId, string, string]>([
        ['evaluation-runs', urls.aiObservabilityEvaluation('e1'), 'evals'],
        ['cluster-traces', urls.aiObservabilityCluster('run-1', 3), 'summary'],
    ])('links to the full page of %s on the view it opened', (listId, path, tab) => {
        setUp({ url: `${path}?tab=stale&trace=a&step=x`, listId })

        expect(combineUrl(logic.values.fullPageHref ?? '').searchParams).toMatchObject({ tab, event: 'x' })
    })

    it('links to the full page with the back target of its own list, without the project prefix', () => {
        setUp({
            url: '/project/1/prompt-management/prompts/p1?tab=usage&trace=a&ts=2026&step=x',
            listId: 'prompt-traces',
        })

        const { searchParams } = combineUrl(logic.values.fullPageHref ?? '')

        expect(searchParams).toMatchObject({
            back_to: 'prompt',
            back_url: '/prompt-management/prompts/p1?tab=usage',
        })
    })

    it('links a queue trace to the full page with the back target and queue the legacy page understands', () => {
        setUp({ url: `${urls.aiObservabilityReviews()}?queue_id=q1&trace=a`, listId: 'review-queue' })

        expect(combineUrl(logic.values.fullPageHref ?? '').searchParams).toMatchObject({
            back_to: 'reviews',
            queue_id: 'q1',
        })
    })

    it('has no full page link while closed', () => {
        setUp()

        expect(logic.values.fullPageHref).toBeNull()
    })
})
