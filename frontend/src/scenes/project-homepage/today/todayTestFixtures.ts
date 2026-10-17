import type { HighlightItemApi, HighlightsApi, SignalViewApi } from 'products/today/frontend/generated/api.schemas'

export function signal(overrides: Partial<SignalViewApi>): SignalViewApi {
    return {
        signal_id: 'signal-1',
        content: '',
        source_product: 'signals_scout',
        source_type: 'cross_source_issue',
        source_id: 'source-1',
        timestamp: '2026-10-01T10:00:00Z',
        extra: {},
        headline: '',
        lead: '',
        meta: '',
        cited: null,
        recording: null,
        link: null,
        preview: null,
        ...overrides,
    }
}

export function makeHighlightItem(overrides: Partial<HighlightItemApi> = {}): HighlightItemApi {
    return {
        key: 'alert:a',
        label: 'risk',
        priority: 'P1',
        title: 'Alert',
        detail: '',
        url: null,
        series: null,
        score: 0.9,
        source: 'alerts',
        ...overrides,
    }
}

export function makeHighlights(overrides: Partial<HighlightsApi> = {}): HighlightsApi {
    return {
        status: 'ready',
        generated_at: '2026-09-30T06:00:00Z',
        day: '2026-09-30',
        refresh_at: '2026-10-01T00:00:00Z',
        pulse: [],
        items: [],
        ...overrides,
    }
}
