import type { LlmAnalyticsTracesWidgetTrace } from './LlmAnalyticsTracesWidgetRow'

export const llmAnalyticsTracesSampleTraces: LlmAnalyticsTracesWidgetTrace[] = [
    {
        id: 'overview-trace-1',
        traceName: 'support_agent',
        createdAt: '2026-05-26T08:04:08.000Z',
        totalLatency: 4.21,
        totalCost: 0.0123,
        inputTokens: 1840,
        outputTokens: 412,
        person: { distinct_id: 'user-1', properties: { email: 'alex@example.test' } },
    },
    {
        id: 'overview-trace-2',
        traceName: 'rag_pipeline',
        createdAt: '2026-05-26T07:58:21.000Z',
        totalLatency: 12.8,
        totalCost: 0.0461,
        inputTokens: 9120,
        outputTokens: 1303,
        errorCount: 1,
        person: { distinct_id: 'user-2', properties: { email: 'sam@example.test' } },
    },
    {
        id: 'overview-trace-3',
        traceName: 'summarizer',
        createdAt: '2026-05-26T07:41:05.000Z',
        totalLatency: 2.04,
        totalCost: 0.0039,
        inputTokens: 640,
        outputTokens: 188,
        person: { distinct_id: 'user-3', properties: { email: 'jordan@example.test' } },
    },
]
