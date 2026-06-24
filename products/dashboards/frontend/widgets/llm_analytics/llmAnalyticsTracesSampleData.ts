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
        distinctId: 'user-1',
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
        distinctId: 'user-2',
    },
    {
        id: 'overview-trace-3',
        traceName: 'summarizer',
        createdAt: '2026-05-26T07:41:05.000Z',
        totalLatency: 2.04,
        totalCost: 0.0039,
        inputTokens: 640,
        outputTokens: 188,
        distinctId: 'user-3',
    },
]
