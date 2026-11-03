import { decodeParams, router } from 'kea-router'
import { getRouterContext } from 'kea-router/lib/router'
import posthog from 'posthog-js'

import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { addProductIntent } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { traceDrawerLogic } from './traceDrawerLogic'
import { TraceListRow } from './traceListRows'
import { traceViewHostLogic } from './traceViewHostLogic'
import { traceViewPreferenceLogic } from './traceViewPreferenceLogic'

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

    function mountDrawer(): void {
        logic = traceDrawerLogic({ listId: 'traces' })
        logic.mount()
        host = traceViewHostLogic({ hostId: logic.values.hostId })
        host.mount()
    }

    function setUp({ url = LIST_PATH, flag = true }: { url?: string; flag?: boolean } = {}): void {
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
        mountDrawer()
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
        host.actions.requestStep('y')
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

    it('goes back through each trace it stepped through, and back to the list', () => {
        setUp()
        logic.actions.setRows([A, B, C])
        logic.actions.openRow(A)
        logic.actions.stepTo('next')
        host.actions.requestStep('b-step')
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
        ['a requested step', (): void => host.actions.requestStep('gen-2')],
        ['closing', (): void => logic.actions.close()],
    ])('keeps the other params and the hash when %s', (_name, write) => {
        setUp({ url: `${LIST_PATH}?trace_search=1.50&date_from=-7d&trace=1.50&ts=2.50&step=3.50#panel=discussion` })
        logic.actions.setRows([{ traceId: '1.50', timestamp: '2.50', stepId: '3.50' }, B])

        write()

        expect(param('trace_search')).toBe('1.50')
        expect(param('date_from')).toBe('-7d')
        expect(router.values.hashParams).toEqual({ panel: 'discussion' })
    })

    it('keeps the raw open trace when a step is written', () => {
        setUp({ url: `${LIST_PATH}?trace=1.50&ts=2.50` })

        host.actions.requestStep('gen-2')

        expect(logic.values.openRef).toEqual({ traceId: '1.50', timestamp: '2.50', stepId: 'gen-2' })
        expect(browserHistory).toHaveLength(1)
    })

    it('does not write a step the URL already holds', () => {
        setUp({ url: `${LIST_PATH}?trace=a&step=1.50` })
        const replaceState = jest.spyOn(routerHistory(), 'replaceState')

        host.actions.requestStep('1.50')

        expect(replaceState).not.toHaveBeenCalled()
    })

    it('leaves the list URL alone for a step requested while closed', () => {
        setUp()

        host.actions.requestStep('gen-2')

        expect(param('step')).toBeNull()
    })

    it('hands the host the step before the new trace renders', () => {
        setUp()
        logic.actions.setRows([A, B])

        logic.actions.openRow(A)
        expect(host.values.requestedStepId).toBe('x')

        logic.actions.stepTo('next')
        expect(host.values.requestedStepId).toBeNull()
    })

    it.each([
        ['the flag is off', (): void => undefined, false],
        ['the person is on the old view', (): void => traceViewPreferenceLogic.actions.switchView('legacy'), true],
    ])('sends a link to the trace page, without tracking, when %s', (_name, prepare, flag) => {
        setUp({ flag })
        prepare()
        logic.unmount()
        goTo(`${LIST_PATH}?date_from=-7d&trace=a%2Fb&ts=2026-01-01&step=gen-1`)

        mountDrawer()

        expect(logic.values.isEnabled).toBe(false)
        expect(router.values.location.pathname).toContain(urls.aiObservabilityTrace('a/b'))
        expect(router.values.searchParams).toEqual({ timestamp: '2026-01-01', event: 'gen-1' })
        expect(capturedEvents()).toEqual([])
        expect(addProductIntent).not.toHaveBeenCalled()
    })

    it('strips its params on unmount, so changing tab closes the drawer', () => {
        setUp({ url: `${LIST_PATH}?trace_search=1.50&trace=a&ts=2026&step=x` })
        logic.actions.setRows([A, B])
        logic.actions.stepTo('next')

        host.unmount()
        logic.unmount()

        expect(router.values.location.search).toBe('?trace_search=1.50')
        expect(capturedEvents()).toContainEqual(['llma trace drawer closed', { steps: 1 }])
    })

    it.each(['/ai-observability/generations', '/project/1/ai-observability/generations'])(
        'still strips its params from the tab %s',
        (tabPath) => {
            setUp()
            goTo(`${tabPath}?date_from=-7d&trace=a&ts=2026&step=x`)

            logic.unmount()

            expect(router.values.location.search).toBe('?date_from=-7d')
        }
    )

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
        host.actions.requestStep('gen-2')

        const href = logic.values.fullPageHref ?? ''

        expect(href.split('?')[0]).toBe(urls.aiObservabilityTrace('a/b#c'))
        expect(Object.fromEntries(new URLSearchParams(href.split('?')[1]))).toEqual({
            trace_search: '1.50',
            date_from: '-7d',
            timestamp: '2026-01-01',
            event: 'gen-2',
            back_to: 'traces',
        })
    })

    it('has no full page link while closed', () => {
        setUp()

        expect(logic.values.fullPageHref).toBeNull()
    })
})
