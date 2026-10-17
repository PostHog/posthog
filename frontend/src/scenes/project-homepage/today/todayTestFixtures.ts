import type { HighlightItemApi, HighlightsApi } from 'products/today/frontend/generated/api.schemas'

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
