import { RenderResult, act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { combineUrl, router } from 'kea-router'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
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
    makeTraceResource,
} from './adapter/testFixtures'
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

type TraceReply = () => Promise<[number, unknown]>

const answerTrace = (traceId: string): TraceReply => {
    return async () => [200, makeTraceResource({ name: `answer-${traceId}`, defaultNodeId: 'gen-1' })]
}

function useTraceMocks(firstTraceReply: TraceReply): void {
    useMocks({
        get: {
            [`${TRACE_BASE_URL}/`]: ({ params }) => {
                const traceId = decodeIdSegment(String(params.id))
                return traceId === 'a' ? firstTraceReply() : answerTrace(traceId)()
            },
            [`${TRACE_BASE_URL}/nodes/:node_id/`]: ({ params }) => [
                200,
                makeNodeDetail({ id: decodeIdSegment(String(params.node_id)) }),
            ],
            [`${TRACE_BASE_URL}/evaluations/`]: () => [200, makeEvaluationResults()],
            [`${TRACE_BASE_URL}/clusters/`]: () => [200, { clusters: [] }],
            [`${TRACE_BASE_URL}/feedback/`]: () => [200, makeFeedback({ scores: [], responses: [] })],
            [`${TRACE_BASE_URL}/summary/`]: () => [404, { detail: 'No summary yet.' }],
        },
    })
}

function setUp(url: string, sceneRect: Partial<DOMRect> = {}): void {
    initKeaTests()
    localStorage.clear()
    featureFlagLogic.mount()
    featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN], {
        [FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN]: true,
    })
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
        [
            'loading',
            (view) => view.findByLabelText('Loading trace'),
            () => {
                let release = (): void => {}
                const answered = new Promise<void>((resolve) => {
                    release = resolve
                })
                return {
                    reply: async () => {
                        await answered
                        return answerTrace('a')()
                    },
                    release,
                }
            },
        ],
        [
            'missing',
            (view) => view.findByText("We couldn't load this trace"),
            () => ({ reply: async () => [404, { detail: 'Not found.' }], release: () => {} }),
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

    it.each(['spans', 'summary'] as const)(
        'applies the opening of the list once, so stepping from %s stays there',
        async (mode) => {
            silenceKeaLoadersErrors()
            useTraceMocks(answerTrace('a'))
            setUp(drawerUrl(ROW_A, urls.aiObservabilityCluster('run-1', 3)))
            const view = renderHost([ROW_A, ROW_B], 'cluster-traces')
            const host = traceViewHostLogic({ hostId: traceDrawerLogic({ listId: 'cluster-traces' }).values.hostId })
            await waitFor(() => expect(host.values.mode).toBe('summary'))
            act(() => host.actions.setMode(mode))

            fireEvent.click(attr(view.container, 'trace-drawer-next'))

            await view.findAllByText('answer-b')
            expect(host.values.mode).toBe(mode)
        }
    )

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
