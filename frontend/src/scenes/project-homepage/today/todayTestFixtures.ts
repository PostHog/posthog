import type {
    HighlightItemApi,
    HighlightMetricApi,
    HighlightsApi,
    NewsEditionApi,
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

const NEWS_SERIES = [41, 40.4, 41.8, 41.2, 40.6, 41.1, 41.6, 40.8, 41.3, 36.2, 33.4, 32.1, 31.6, 31.4]

export const NEWS_EDITION: NewsEditionApi = {
    id: 'edition-1',
    is_sample: false,
    period_start: '2026-09-28',
    lead: {
        id: 'checkout-conversion',
        product: 'product_analytics',
        product_label: 'Product analytics',
        title: 'Checkout conversion fell 12% after the new address form shipped',
        summary: 'Mobile visitors now stop at the address step. Desktop is flat, so the form is the likely cause.',
        change: -12,
        tone: 'risk',
        dive_prompt: 'Why did checkout conversion fall after the address form change, and what should we fix first?',
        metric_label: 'Last 14 days',
        metric_value: '31.4%',
        series: NEWS_SERIES,
        series_labels: NEWS_SERIES.map((_, index) => `Sep ${15 + index}`),
    },
    stories: [
        {
            id: 'firing-alerts',
            product: 'alerts',
            product_label: 'Alerts',
            title: '3 alerts are firing, and 2 point at checkout',
            summary: 'Checkout errors hit the most users. Start there.',
            change: null,
            tone: 'risk',
            dive_prompt: 'Three alerts are firing. Which one should we look at first, and what is the likely cause?',
        },
        {
            id: 'pricing-experiment',
            product: 'experiments',
            product_label: 'Experiments',
            title: 'Variant B of the pricing page won',
            summary: 'More plan clicks, with a 96% chance it is really better. Ready to roll out.',
            change: 8,
            tone: 'good',
            dive_prompt: 'Variant B of the pricing page layout won. What should we do to roll it out safely?',
        },
        {
            id: 'checkout-error',
            product: 'error_tracking',
            product_label: 'Error tracking',
            title: 'A new checkout error hit 214 users',
            summary: 'It started on Tuesday, and nobody owns it yet.',
            change: null,
            tone: 'risk',
            dive_prompt: 'A new checkout error reached 214 users. What causes it, and how do we fix it?',
        },
    ],
    briefs: ['2 experiments started', '12 new feature flags', '41 deploys to production'],
}
