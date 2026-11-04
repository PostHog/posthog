import type {
    HighlightItemApi,
    HighlightMetricApi,
    HighlightsApi,
    SignalViewApi,
} from 'products/today/frontend/generated/api.schemas'

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

export function makePulseMetric(overrides: Partial<HighlightMetricApi> = {}): HighlightMetricApi {
    return {
        key: 'insight:abc',
        name: 'Sign-ups',
        value: 120,
        unit: 'number',
        change_pct: 4,
        series: [100, 120],
        interval: 'week',
        url: '/insights/abc',
        value_format: null,
        period_starts: ['2026-09-21', '2026-09-28'],
        reason: 'routine',
        dashboard_name: null,
        dashboard_id: null,
        opened_days: 5,
        last_opened: '2026-09-29',
        movers: [],
        previous_value: 100,
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
        pins: [],
        ...overrides,
    }
}
