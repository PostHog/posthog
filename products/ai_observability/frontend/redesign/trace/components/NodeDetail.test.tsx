import { cleanup, render, screen } from '@testing-library/react'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import type { TraceEvaluationResultApi, TraceNodeApi } from '../../../generated/api.schemas'
import { makeEvaluationResult, makeNodeDetail, makeTraceResource } from '../testFixtures'
import { NodeDetailTab, NodeLoad } from '../types'
import { NodeDetail, NodeDetailProps } from './NodeDetail'

const TRACE = { ...makeTraceResource(), sessionId: 'sess-1' }
const [ROOT] = TRACE.tree
const GENERATION: TraceNodeApi = ROOT.children[1]
const STEP_LABELS = new Map([
    ['trace-1', 'answer-billing-question'],
    ['gen-1', 'openai.chat #1'],
    ['gen-2', 'openai.chat #2'],
])

function renderDetail(overrides: Partial<NodeDetailProps> & { node: TraceNodeApi; tab: NodeDetailTab }): void {
    render(
        <NodeDetail
            onTabChange={() => {}}
            load={{ status: 'loading' }}
            trace={TRACE}
            evaluationResults={[]}
            evaluationResultsFailed={false}
            stepLabels={STEP_LABELS}
            raw={undefined}
            onViewInThread={null}
            messagesOpening="lastTurn"
            onMessagesOpeningChange={() => {}}
            onSelectNode={() => {}}
            {...overrides}
        />
    )
}

const result = (overrides: Partial<TraceEvaluationResultApi> = {}): TraceEvaluationResultApi =>
    makeEvaluationResult({ targetNodeId: 'gen-1', ...overrides })

describe('NodeDetail', () => {
    beforeEach(() => {
        initKeaTests()
        Element.prototype.scrollIntoView = jest.fn()
    })

    afterEach(() => {
        cleanup()
    })

    it.each<[string, NodeLoad, string]>([
        [
            'not found',
            { status: 'error', failure: 'not_found' },
            'This step could not be found. It may have been deleted, or it is outside the retention period.',
        ],
        ['failed', { status: 'error', failure: 'failed' }, 'This step could not be loaded. Select it again to retry.'],
    ])('explains a step that %s', (_name, load, message) => {
        renderDetail({ node: GENERATION, tab: 'messages', load })

        expect(screen.getByText(message)).toBeTruthy()
    })

    it('shows a step its event time and settings, and the trace person', () => {
        const detail = makeNodeDetail({
            id: 'gen-1',
            metadata: {
                provider: 'openai',
                temperature: 0.2,
                sessionId: 'sess-9',
                promptName: 'answer',
                promptVersion: 6,
            },
        })

        renderDetail({ node: GENERATION, tab: 'details', load: { status: 'ready', node: detail } })

        expect(screen.getByText('openai')).toBeTruthy()
        expect(screen.getByText('0.2')).toBeTruthy()
        expect(screen.getByText('sess-9')).toBeTruthy()
        expect(screen.getByText('answer v6')).toBeTruthy()
    })

    it('shows the root the trace session and person without waiting for its step read', () => {
        renderDetail({ node: ROOT, tab: 'details' })

        expect(screen.getByText('sess-1')).toBeTruthy()
        expect(screen.getByText('ada@example.com')).toBeTruthy()
    })

    it('lists only the results of the viewed step, or every result on the root', () => {
        const results = [
            result({ id: 'r1', evaluationName: 'Own' }),
            result({ id: 'r2', evaluationName: 'Other', targetNodeId: 'gen-2' }),
        ]

        renderDetail({ node: GENERATION, tab: 'evals', evaluationResults: results })
        expect(screen.getByText('Own')).toBeTruthy()
        expect(screen.queryByText('Other')).toBeNull()
        cleanup()

        renderDetail({ node: ROOT, tab: 'evals', evaluationResults: results })
        expect(screen.getByText('Other')).toBeTruthy()
    })

    it.each([
        ['another step by its label', 'gen-2', 'openai.chat #2'],
        ['a step missing from the tree by a short id', 'gen-0123456789abcdef', 'gen-01234567...'],
    ])('names the target of a result on %s', (_name, targetNodeId, label) => {
        renderDetail({ node: ROOT, tab: 'evals', evaluationResults: [result({ targetNodeId })] })

        expect(screen.getByText(label)).toBeTruthy()
    })

    it('links a result to its evaluation and names no target on the step it grades', () => {
        renderDetail({ node: GENERATION, tab: 'evals', evaluationResults: [result()] })

        expect(screen.getByText('Answers the question').closest('a')?.getAttribute('href')).toContain(
            urls.aiObservabilityEvaluation('ev-helpful')
        )
        expect(document.querySelector('[data-attr="trace-view-eval-target"]')).toBeNull()
    })

    it('explains evaluation results that failed to load', () => {
        renderDetail({ node: GENERATION, tab: 'evals', evaluationResults: null, evaluationResultsFailed: true })

        expect(screen.getByText('Evaluation results could not be loaded. Reload the page to try again.')).toBeTruthy()
    })
})
