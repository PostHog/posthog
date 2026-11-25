import { RenderResult, act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { combineUrl, router } from 'kea-router'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { aiObservabilityTracesNodesRetrieve } from '../../generated/api'
import {
    decodeIdSegment,
    makeEvaluationResults,
    makeFeedback,
    makeNodeDetail,
    makeSeededRow,
    makeTraceResource,
} from './testFixtures'
import { TraceDrawerHost } from './TraceDrawerHost'
import type { TraceDrawerListId } from './traceDrawerLists'
import { traceDrawerLogic } from './traceDrawerLogic'
import { TraceListRow } from './traceListRows'
import { traceViewHostLogic } from './traceViewHostLogic'

jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))
jest.mock('../../generated/api', () => {
    const actual = jest.requireActual('../../generated/api')
    return {
        ...actual,
        aiObservabilityTracesNodesRetrieve: jest.fn(actual.aiObservabilityTracesNodesRetrieve),
    }
})
jest.mock('../../utils', () => ({
    ...jest.requireActual('../../utils'),
    queryEvaluationRuns: jest.fn().mockResolvedValue([]),
}))

const TRACE_BASE_URL = '/api/projects/:team_id/ai_observability/traces/:id'
const LIST_PATH = urls.aiObservabilityTraces()
const LIST_ID: TraceDrawerListId = 'traces'
const ROW_A: TraceListRow = { traceId: 'a', timestamp: '2026-09-01T10:15:00Z', stepId: null }
const ROW_B: TraceListRow = { traceId: 'b', timestamp: '2026-09-01T10:20:00Z', stepId: null }
const SEEDED_ROW_A = makeSeededRow({ id: 'a', name: 'row-a' })
const SEEDED_ROW_B = makeSeededRow({ id: 'b', name: 'row-b', createdAt: '2026-09-01T10:20:00Z' }, 'gen-1')

type TraceReply = () => Promise<[number, unknown]>

const answerTrace = (traceId: string): TraceReply => {
    return async () => [200, makeTraceResource({ name: `answer-${traceId}`, defaultNodeId: 'gen-1' })]
}

const notFound: TraceReply = async () => [404, { detail: 'Not found.' }]

function held(reply: TraceReply): { reply: TraceReply; release: () => void } {
    let release = (): void => {}
    const answered = new Promise<void>((resolve) => {
        release = resolve
    })
    return {
        reply: async () => {
            await answered
            return reply()
        },
        release,
    }
}

function useTraceMocks(firstTraceReply: TraceReply, nextTraceReply: TraceReply = answerTrace('b')): void {
    useMocks({
        get: {
            [`${TRACE_BASE_URL}/`]: ({ params }) => {
                const traceId = decodeIdSegment(String(params.id))
                return traceId === 'a' ? firstTraceReply() : traceId === 'b' ? nextTraceReply() : answerTrace(traceId)()
            },
            [`${TRACE_BASE_URL}/nodes/:node_id/`]: ({ params }) => [
                200,
                makeNodeDetail({ id: decodeIdSegment(String(params.node_id)) }),
            ],
            [`${TRACE_BASE_URL}/evaluations/`]: () => [200, makeEvaluationResults()],
            [`${TRACE_BASE_URL}/clusters/`]: () => [200, { clusters: [] }],
            [`${TRACE_BASE_URL}/feedback/`]: () => [200, makeFeedback({ scores: [], responses: [] })],
            [`${TRACE_BASE_URL}/summary/`]: () => [404, { detail: 'No summary yet.' }],
            [`${TRACE_BASE_URL}/search/`]: () => [200, { total: 0, matches: [] }],
        },
    })
}

function setUp(url: string, sceneRect: Partial<DOMRect> = {}): void {
    initKeaTests()
    localStorage.clear()
    featureFlagLogic.mount()
    panelLayoutLogic.mount()
    panelLayoutLogic.actions.setMainContentRect(Object.assign(document.body.getBoundingClientRect(), sceneRect))
    router.actions.push(url)
}

function drawerUrl({ traceId, timestamp }: TraceListRow, listPath: string = LIST_PATH): string {
    return combineUrl(listPath, { trace: traceId, ts: timestamp ?? undefined }).url
}

function renderHost(rows: TraceListRow[], listId: TraceDrawerListId = LIST_ID): RenderResult {
    const logic = traceDrawerLogic({ listId })
    logic.mount()
    logic.actions.setRows(rows)
    return render(<TraceDrawerHost listId={listId} />)
}

function attr(container: Element, name: string): HTMLElement {
    const element = container.querySelector<HTMLElement>(`[data-attr="${name}"]`)
    if (!element) {
        throw new Error(`expected ${name} to render`)
    }
    return element
}

function headerName(view: RenderResult): string | null {
    return view.container.querySelector('h1')?.textContent ?? null
}

const PARTIAL_HINT = /covers those steps only/

function hover(element: HTMLElement): void {
    fireEvent.pointerEnter(element, { pointerType: 'mouse' })
    fireEvent.mouseEnter(element)
    fireEvent.pointerMove(element, { pointerType: 'mouse' })
    fireEvent.mouseMove(element)
}

// jsdom leaves pageX out of mouse events, and the resizer measures the drag with it.
function mouseEventAt(type: string, pageX: number): MouseEvent {
    const event = new MouseEvent(type, { button: 0, bubbles: true })
    Object.defineProperty(event, 'pageX', { value: pageX })
    return event
}

describe('TraceDrawerHost', () => {
    afterEach(() => {
        cleanup()
        resumeKeaLoadersErrors()
    })

    it.each<[string, (view: RenderResult) => Promise<HTMLElement>, () => { reply: TraceReply; release: () => void }]>([
        ['loading', (view) => view.findByLabelText('Loading trace'), () => held(answerTrace('a'))],
        [
            'missing',
            (view) => view.findByText("We couldn't load this trace"),
            () => ({ reply: notFound, release: () => {} }),
        ],
    ])('keeps the toolbar and moves on from a %s trace', async (_name, findScreen, makeReply) => {
        silenceKeaLoadersErrors()
        const { reply, release } = makeReply()
        useTraceMocks(reply)
        setUp(drawerUrl(ROW_A))
        const view = renderHost([ROW_A, ROW_B])
        await findScreen(view)
        const close = attr(view.container, 'trace-drawer-close')
        const host = traceViewHostLogic({ hostId: traceDrawerLogic({ listId: LIST_ID }).values.hostId })
        act(() => host.actions.setMode('thread'))

        expect(view.getByText('1 of 2')).toBeTruthy()
        expect(view.queryByText(/^Back to/)).toBeNull()
        expect(view.container.querySelector('[data-attr="trace-view-back"]')).toBeNull()

        fireEvent.click(attr(view.container, 'trace-drawer-next'))

        expect((await view.findAllByText('answer-b')).length).toBeGreaterThan(0)
        expect(view.getByText('2 of 2')).toBeTruthy()
        expect(router.values.searchParams.trace).toBe('b')
        expect(attr(view.container, 'trace-drawer-close')).toBe(close)
        expect(host.values.mode).toBe('thread')
        release()
    })

    it("shows the row's name, person and partial totals while the trace loads, then the trace's", async () => {
        const totals = { ...makeTraceResource().totals, inputTokens: 1840 }
        const row: TraceListRow = {
            ...makeSeededRow({ id: 'a', name: 'row-a', totals, totalsPartial: true }),
            person: { distinctId: 'row-person', label: 'row-person@example.com' },
        }
        const { reply, release } = held(async () => [200, makeTraceResource({ name: 'answer-a', totals })])
        useTraceMocks(reply)
        setUp(drawerUrl(row))
        const view = renderHost([row])

        expect(await view.findByText('row-a')).toBeTruthy()
        expect(view.getByText('row-person@example.com')).toBeTruthy()
        expect(view.getByLabelText('Loading trace')).toBeTruthy()
        expect(attr(view.container, 'trace-view-copy').getAttribute('aria-disabled')).toBe('true')
        expect(attr(view.container, 'trace-view-export').getAttribute('aria-disabled')).toBe('true')
        fireEvent.change(attr(view.container, 'trace-view-search-input'), { target: { value: 'weather' } })
        expect(await view.findByText('Searching…')).toBeTruthy()
        hover(view.getByText('1,840 in'))
        expect(await view.findByText(PARTIAL_HINT)).toBeTruthy()

        release()
        expect((await view.findAllByText('answer-a')).length).toBeGreaterThan(0)
        expect(attr(view.container, 'trace-view-copy').getAttribute('aria-disabled')).toBe('false')
        expect(attr(view.container, 'trace-view-export').getAttribute('aria-disabled')).toBe('false')
        expect(await view.findByText('No matches')).toBeTruthy()
        expect(view.queryByText('row-a')).toBeNull()
        expect(view.queryByText('row-person@example.com')).toBeNull()
        expect(view.getByText('ada@example.com')).toBeTruthy()
        hover(view.getByText('1,840 in'))
        // Longer than the tooltip's open delay, so a marker that survived the answer would show its hint again.
        await expect(view.findByText(PARTIAL_HINT)).rejects.toThrow()
    })

    it("drops the row's person once the trace answers with no person", async () => {
        const row: TraceListRow = {
            ...SEEDED_ROW_A,
            person: { distinctId: 'row-person', label: 'row-person@example.com' },
        }
        const { reply, release } = held(async () => [200, makeTraceResource({ name: 'answer-a', person: null })])
        useTraceMocks(reply)
        setUp(drawerUrl(row))
        const view = renderHost([row])

        expect(await view.findByText('row-person@example.com')).toBeTruthy()

        release()
        expect((await view.findAllByText('answer-a')).length).toBeGreaterThan(0)
        expect(view.queryByText('row-person@example.com')).toBeNull()
    })

    it('shows the error alone when the read fails after the header was seeded', async () => {
        silenceKeaLoadersErrors()
        const { reply, release } = held(notFound)
        useTraceMocks(reply)
        setUp(drawerUrl(SEEDED_ROW_A))
        const view = renderHost([SEEDED_ROW_A])
        expect(await view.findByText('row-a')).toBeTruthy()

        release()
        await view.findByText("We couldn't load this trace")

        expect(view.queryByText('row-a')).toBeNull()
    })

    it.each<[string, () => void]>([
        ['next', () => fireEvent.click(attr(document.body, 'trace-drawer-next'))],
        [
            'a click on another row',
            () => act(() => traceDrawerLogic({ listId: LIST_ID }).actions.openRow(SEEDED_ROW_B)),
        ],
    ])('steps to the next trace with its row header and a loading body through %s', async (_name, stepToB) => {
        const next = held(answerTrace('b'))
        useTraceMocks(answerTrace('a'), next.reply)
        setUp(drawerUrl(SEEDED_ROW_A))
        const view = renderHost([SEEDED_ROW_A, SEEDED_ROW_B])
        await view.findAllByText('answer-a')

        stepToB()

        expect(headerName(view)).toBe('row-b')
        expect(view.queryAllByText('answer-a')).toEqual([])
        expect(view.getByLabelText('Loading trace')).toBeTruthy()
        expect(view.getByText('2 of 2')).toBeTruthy()

        next.release()
        await waitFor(() => expect(headerName(view)).toBe('answer-b'))
        expect(view.queryByLabelText('Loading trace')).toBeNull()
    })

    it('steps to a row without an overview with the full skeleton', async () => {
        const next = held(answerTrace('b'))
        useTraceMocks(answerTrace('a'), next.reply)
        setUp(drawerUrl(ROW_A))
        const view = renderHost([ROW_A, ROW_B])
        await view.findAllByText('answer-a')

        fireEvent.click(attr(view.container, 'trace-drawer-next'))

        expect(headerName(view)).toBeNull()
        expect(view.queryAllByText('answer-a')).toEqual([])
        expect(view.getByLabelText('Loading trace')).toBeTruthy()

        next.release()
        await waitFor(() => expect(headerName(view)).toBe('answer-b'))
    })

    it.each([
        ['spans', 'toolbar'],
        ['summary', 'toolbar'],
        ['spans', 'list'],
        ['summary', 'list'],
    ] as const)('keeps the selected %s view when opening another trace from the %s', async (mode, source) => {
        silenceKeaLoadersErrors()
        useTraceMocks(answerTrace('a'))
        setUp(drawerUrl(ROW_A, urls.aiObservabilityCluster('run-1', 3)))
        const view = renderHost([ROW_A, ROW_B], 'cluster-traces')
        const drawer = traceDrawerLogic({ listId: 'cluster-traces' })
        const host = traceViewHostLogic({ hostId: drawer.values.hostId })
        await waitFor(() => expect(host.values.mode).toBe('thread'))
        act(() => host.actions.setMode(mode))

        const list = render(
            <LemonButton data-attr="open-trace-b" onClick={() => drawer.actions.openRow(ROW_B)}>
                Open trace B
            </LemonButton>
        )
        const target =
            source === 'list' ? attr(list.container, 'open-trace-b') : attr(view.container, 'trace-drawer-next')
        fireEvent.mouseDown(target)
        fireEvent.mouseUp(target)
        fireEvent.click(target)

        await view.findAllByText('answer-b')
        expect(router.values.searchParams.trace).toBe('b')
        expect(host.values.mode).toBe(mode)
    })

    it('steps with n and p, but not while typing or with a modal open', async () => {
        useTraceMocks(answerTrace('a'))
        setUp(drawerUrl(ROW_A))
        const view = renderHost([ROW_A, ROW_B])
        await view.findAllByText('answer-a')

        fireEvent.keyDown(attr(view.container, 'trace-view-search-input'), { key: 'n' })
        expect(router.values.searchParams.trace).toBe('a')

        const modal = render(
            <LemonModal isOpen onClose={() => {}} title="Edit dataset item">
                <LemonButton>Save</LemonButton>
            </LemonModal>
        )
        fireEvent.keyDown(modal.getByText('Save'), { key: 'n' })
        modal.unmount()
        expect(router.values.searchParams.trace).toBe('a')

        fireEvent.keyDown(document.body, { key: 'n' })
        await waitFor(() => expect(router.values.searchParams.trace).toBe('b'))

        fireEvent.keyDown(document.body, { key: 'p' })
        await waitFor(() => expect(router.values.searchParams.trace).toBe('a'))
    })

    it('steps through the tree with j and k, but not with a modal open, and its legend names the trace keys', async () => {
        useTraceMocks(answerTrace('a'))
        setUp(drawerUrl(ROW_A))
        const view = renderHost([ROW_A, ROW_B])
        await view.findByText('span-1')
        expect(attr(view.container, 'trace-view-tree-key-legend').textContent).toContain('traces')

        const modal = render(
            <LemonModal isOpen onClose={() => {}} title="Edit dataset item">
                <LemonButton>Save</LemonButton>
            </LemonModal>
        )
        fireEvent.keyDown(modal.getByText('Save'), { key: 'j' })
        modal.unmount()
        expect(router.values.searchParams.step).toBeUndefined()

        fireEvent.keyDown(document.body, { key: 'k' })
        await waitFor(() => expect(router.values.searchParams.step).toBe('span-1'))
    })

    it('reads no node when it closes on a step other than the default', async () => {
        useTraceMocks(answerTrace('a'))
        setUp(combineUrl(LIST_PATH, { trace: 'a', ts: ROW_A.timestamp ?? undefined, step: 'span-1' }).url)
        const view = renderHost([ROW_A])
        await view.findAllByText('answer-a')
        await waitFor(() => expect(aiObservabilityTracesNodesRetrieve).toHaveBeenCalled())
        jest.mocked(aiObservabilityTracesNodesRetrieve).mockClear()

        fireEvent.click(attr(view.container, 'trace-drawer-close'))

        expect(router.values.searchParams.trace).toBeUndefined()
        expect(aiObservabilityTracesNodesRetrieve).not.toHaveBeenCalled()
    })

    it('writes a clicked step to the list URL and stays on the list', async () => {
        useTraceMocks(answerTrace('a'))
        setUp(drawerUrl(ROW_A))
        const { findByText } = renderHost([ROW_A])

        fireEvent.click(await findByText('span-1'))

        await waitFor(() => expect(router.values.searchParams.step).toBe('span-1'))
        expect(router.values.location.pathname).toContain(LIST_PATH)
        expect(router.values.searchParams.event).toBeUndefined()
    })

    it('opens at two thirds of the scene and follows the resizer', async () => {
        useTraceMocks(answerTrace('a'))
        setUp(drawerUrl(ROW_A), { width: 1200 })
        const { container, findAllByText } = renderHost([ROW_A])
        await findAllByText('answer-a')
        const panel = attr(container, 'trace-drawer')
        expect(panel.style.width).toBe('800px')

        const resizer = container.querySelector('.Resizer')
        if (!resizer) {
            throw new Error('expected the panel to render a resizer')
        }

        fireEvent(resizer, mouseEventAt('mousedown', 1000))
        fireEvent(document, mouseEventAt('mouseup', 100))

        await waitFor(() => expect(panel.style.width).toBe('900px'))
    })

    it('has no resizer when the panel takes the whole scene', async () => {
        useTraceMocks(answerTrace('a'))
        setUp(drawerUrl(ROW_A), { width: 800 })
        const { container, findAllByText } = renderHost([ROW_A])
        await findAllByText('answer-a')

        expect(attr(container, 'trace-drawer').style.width).toBe('800px')
        expect(container.querySelector('.Resizer')).toBeNull()
    })
})
