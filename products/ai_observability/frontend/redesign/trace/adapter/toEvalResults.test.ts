import { urls } from 'scenes/urls'

import type { TraceNodeApi } from '../../../generated/api.schemas'
import { makeEvaluationResult } from './testFixtures'
import { toEvalResults } from './toEvalResults'

const node = (id: string, kind: TraceNodeApi['kind'], name: string, children: TraceNodeApi[] = []): TraceNodeApi => ({
    id,
    kind,
    name,
    model: null,
    hasError: false,
    children,
    stats: {
        costUsd: null,
        inputTokens: null,
        outputTokens: null,
        cacheReadTokens: null,
        cacheWriteTokens: null,
        latencyMs: null,
    },
})

const tree = [
    node('trace-1', 'trace', 'answer-billing-question', [
        node('gen-1', 'generation', 'gpt-4.1-mini (openai)'),
        node('span-1', 'span', 'lookup-invoice'),
        node('gen-2', 'generation', 'gpt-4.1-mini (openai)'),
    ]),
]

describe('toEvalResults', () => {
    it.each([
        ['a trace-level result seen on the root targets nothing', 'trace-1', 'trace-1', null],
        [
            'a result on a generation seen on the root names that generation apart from its namesake',
            'trace-1',
            'gen-2',
            { nodeId: 'gen-2', label: 'gpt-4.1-mini (openai) #2' },
        ],
        ['a result on the viewed generation targets nothing', 'gen-1', 'gen-1', null],
        [
            'a result on a node missing from the tree falls back to a short id',
            'trace-1',
            'gen-0123456789abcdef',
            { nodeId: 'gen-0123456789abcdef', label: 'gen-01234567...' },
        ],
    ])('%s', (_name, viewedNodeId, targetNodeId, expected) => {
        const [result] = toEvalResults([makeEvaluationResult({ targetNodeId })], { tree, viewedNodeId })
        expect(result.target).toEqual(expected)
    })

    it.each([
        ['an evaluation id links to its evaluation', 'ev-helpful', urls.aiObservabilityEvaluation('ev-helpful')],
        ['a result with no evaluation id has no link', null, null],
    ])('%s', (_name, evaluationId, href) => {
        const [result] = toEvalResults([makeEvaluationResult({ evaluationId })], { tree, viewedNodeId: 'trace-1' })
        expect(result.href).toBe(href)
    })
})
