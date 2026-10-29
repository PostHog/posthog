import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import type {
    TraceApi,
    TraceClusterApi,
    TraceEvaluationResultApi,
    TraceEvaluationResultsApi,
    TraceFeedbackApi,
    TraceFeedbackScoreApi,
    TraceFeedbackTextApi,
    TraceNodeApi,
    TraceNodeDetailApi,
    TraceNodeIOKeysApi,
    TraceNodeMetadataApi,
    TraceNodeStatsApi,
    TraceSurveyResponseApi,
} from '../../../generated/api.schemas'

export function makeEvent(overrides: Partial<LLMTraceEvent> & { id: string }): LLMTraceEvent {
    return { event: '$ai_span', properties: {}, createdAt: '2026-09-01T10:15:00Z', ...overrides }
}

export function makeTrace(overrides: Partial<LLMTrace> = {}): LLMTrace {
    return {
        id: 'trace-1',
        createdAt: '2026-09-01T10:15:00Z',
        distinctId: 'user-ana',
        traceName: 'answer-billing-question',
        totalCost: 0.0021,
        inputTokens: 1840,
        outputTokens: 212,
        totalLatency: 2.31,
        events: [],
        ...overrides,
    }
}

const emptyStats: TraceNodeStatsApi = {
    costUsd: null,
    inputTokens: null,
    outputTokens: null,
    cacheReadTokens: null,
    cacheWriteTokens: null,
    latencyMs: null,
}

export function decodeIdSegment(segment: string): string {
    const binary = atob(segment.replace(/-/g, '+').replace(/_/g, '/'))
    return new TextDecoder().decode(Uint8Array.from(binary, (char) => char.charCodeAt(0)))
}

interface NodeDetailFixture {
    id: string
    kind?: TraceNodeApi['kind']
    properties?: Record<string, unknown>
    ioKeys?: Partial<TraceNodeIOKeysApi>
    error?: string | null
    metadata?: Partial<TraceNodeMetadataApi>
    withEvent?: boolean
}

export function makeNodeDetail({
    id,
    kind = 'generation',
    properties = {},
    ioKeys = {},
    error = null,
    metadata = {},
    withEvent = true,
}: NodeDetailFixture): TraceNodeDetailApi {
    return {
        id,
        kind,
        error,
        metadata: {
            provider: null,
            temperature: null,
            sessionId: null,
            promptName: null,
            promptVersion: null,
            ...metadata,
        },
        event: withEvent
            ? {
                  name: `$ai_${kind}`,
                  uuid: id,
                  timestamp: '2026-09-01T10:15:02Z',
                  properties,
                  ioKeys: { input: null, output: null, tools: null, ...ioKeys },
              }
            : null,
    }
}

export function makeTraceResource(overrides: Partial<TraceApi> = {}): TraceApi {
    const childIds = ['span-1', 'gen-1', 'gen-2']
    return {
        id: 'trace-1',
        name: 'answer-billing-question',
        createdAt: '2026-09-01T10:15:00Z',
        sessionId: null,
        person: { distinctId: 'user-1', label: 'ada@example.com' },
        totals: emptyStats,
        hasError: false,
        errorCount: 0,
        tree: [
            {
                id: 'trace-1',
                kind: 'trace',
                name: 'answer-billing-question',
                model: null,
                stats: emptyStats,
                hasError: false,
                children: childIds.map((id) => ({
                    id,
                    kind: id.startsWith('gen') ? 'generation' : 'span',
                    name: id,
                    model: null,
                    stats: emptyStats,
                    hasError: false,
                    children: [],
                })),
            },
        ],
        timeline: [],
        totalMs: 0,
        threadNodeIds: ['gen-2'],
        defaultNodeId: 'trace-1',
        nodeIdsByAlias: {},
        git: null,
        ...overrides,
    }
}

export function makeEvaluationResult(overrides: Partial<TraceEvaluationResultApi> = {}): TraceEvaluationResultApi {
    return {
        id: 'r1',
        evaluationId: 'ev-helpful',
        evaluationName: 'Answers the question',
        targetNodeId: 'trace-1',
        outcome: 'pass',
        label: 'True',
        score: null,
        reasoning: 'Direct answer.',
        timestamp: '2026-09-01T10:16:00Z',
        isBackfill: false,
        ...overrides,
    }
}

export function makeTraceCluster(overrides: Partial<TraceClusterApi> = {}): TraceClusterApi {
    return {
        runId: '1_trace_20260902_030000',
        runAt: '2026-09-02T03:40:00Z',
        jobId: '0192f2a4-5c1e-7000-8000-0000000c1a01',
        jobName: 'Support conversations',
        clusterId: 3,
        title: 'Billing questions',
        description: 'Users ask why an invoice changed.',
        isOutlier: false,
        ...overrides,
    }
}

export function makeFeedbackScore(overrides: Partial<TraceFeedbackScoreApi> = {}): TraceFeedbackScoreApi {
    return {
        id: 'score-1',
        name: 'helpfulness',
        value: '0',
        nodeId: 'gen-1',
        timestamp: '2026-09-01T10:16:00Z',
        ...overrides,
    }
}

export function makeFeedbackText(overrides: Partial<TraceFeedbackTextApi> = {}): TraceFeedbackTextApi {
    return {
        kind: 'text',
        id: 'text-1',
        text: 'Too long, but correct.',
        nodeId: 'trace-1',
        timestamp: '2026-09-01T10:17:00Z',
        ...overrides,
    }
}

export function makeSurveyResponse(overrides: Partial<TraceSurveyResponseApi> = {}): TraceSurveyResponseApi {
    return {
        kind: 'survey',
        id: 'submission-1',
        nodeId: 'trace-1',
        timestamp: '2026-09-01T10:18:00Z',
        survey: { id: 'survey-1', name: 'Answer quality' },
        answers: [{ kind: 'thumbs', question: 'Was this answer useful?', up: true }],
        complete: true,
        unavailable: null,
        ...overrides,
    }
}

export function makeFeedback(overrides: Partial<TraceFeedbackApi> = {}): TraceFeedbackApi {
    const scores = overrides.scores ?? [makeFeedbackScore()]
    const responses = overrides.responses ?? [makeFeedbackText()]
    return {
        scores,
        responses,
        unanswered: [],
        surveyResponsesStatus: 'ok',
        summary: { total: scores.length + responses.length, thumbsUp: 0, thumbsDown: 0 },
        ...overrides,
    }
}

export function makeEvaluationResults(overrides: Partial<TraceEvaluationResultsApi> = {}): TraceEvaluationResultsApi {
    return { results: [], summary: { passed: 0, failed: 0, unrated: 0, nodes: [] }, ...overrides }
}
