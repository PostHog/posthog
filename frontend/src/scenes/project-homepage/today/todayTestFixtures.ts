import type {
    HighlightItemApi,
    HighlightMetricApi,
    HighlightsApi,
    NewsChartApi,
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
const NEWS_LABELS = NEWS_SERIES.map((_, index) => `Sep ${15 + index}`)

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
        series_labels: NEWS_LABELS,
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
            chart: newsChart({
                kind: 'line',
                caption: '',
                labels: NEWS_LABELS,
                values: [2, 3, 2, 4, 3, 2, 3, 4, 3, 5, 6, 8, 9, 11],
            }),
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
            chart: newsChart({
                kind: 'line',
                caption: '',
                labels: NEWS_LABELS,
                values: [120, 118, 125, 131, 128, 135, 140, 138, 142, 150, 149, 155, 158, 161],
            }),
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
            chart: newsChart({
                kind: 'line',
                caption: '',
                labels: NEWS_LABELS,
                values: [0, 0, 0, 0, 0, 0, 0, 0, 12, 48, 96, 150, 188, 214],
            }),
        },
    ],
    briefs: [
        {
            id: 'error:slow-search',
            value: 1900,
            text: 'waited on slow search results',
            change: 28,
            is_new: false,
            tone: 'risk',
            series: [1200, 1300, 1250, 1400, 1350, 1300, 1450, 1500, 1480, 1600, 1700, 1750, 1820, 1900],
            series_labels: NEWS_LABELS,
        },
        {
            id: 'error:missing-docs',
            value: 310,
            text: 'hit a missing docs page',
            change: null,
            is_new: true,
            tone: 'risk',
            series: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 40, 120, 260, 310],
            series_labels: NEWS_LABELS,
        },
    ],
    ongoing: [],
    this_week: [],
}

const [ALERTS_STORY, PRICING_STORY, ERROR_STORY] = NEWS_EDITION.stories

function newsChart(chart: Pick<NewsChartApi, 'kind' | 'caption'> & Partial<NewsChartApi>): NewsChartApi {
    return {
        unit: '',
        labels: [],
        values: [],
        items: [],
        higher_is_good: null,
        ...chart,
    }
}

export const NEWS_FRONT_PAGE_EDITION: NewsEditionApi = {
    ...NEWS_EDITION,
    id: 'edition-2',
    stories: [
        {
            ...PRICING_STORY,
            chart: newsChart({
                kind: 'split',
                caption: 'Plan clicks by variant',
                items: [
                    { label: 'Variant B', value: 610 },
                    { label: 'Control', value: 560 },
                ],
            }),
        },
        ALERTS_STORY,
        ERROR_STORY,
    ],
    ongoing: [
        {
            id: 'ongoing-signup-errors',
            product: 'error_tracking',
            product_label: 'Error tracking',
            title: 'Sign-up form errors are still climbing',
            update: '96 people hit the error today, up from 61 yesterday.',
            dive_prompt: 'Sign-up form errors keep climbing. What changed, and how do we fix it?',
            day: 3,
            status: 'worse',
            tone: 'risk',
            series: [8, 10, 9, 12, 30, 61, 96],
            series_labels: NEWS_LABELS.slice(-7),
        },
        {
            id: 'ongoing-docs-traffic',
            product: 'web_analytics',
            product_label: 'Web analytics',
            title: 'Docs traffic is back to normal',
            update: 'Visits returned to the usual level after the search fix.',
            dive_prompt: 'Docs traffic recovered. Did the search fix bring visitors back?',
            day: 4,
            status: 'ended',
            tone: 'good',
            series: [900, 620, 580, 640, 760, 880, 910],
            series_labels: NEWS_LABELS.slice(-7),
        },
    ],
    this_week: [
        {
            id: 'week-ai-features',
            product: 'llm_analytics',
            product_label: 'AI',
            title: 'More people use the AI summary than the AI search',
            summary: 'Weekly AI summary users rose for a third week, while AI search stayed flat.',
            change: null,
            tone: 'good',
            dive_prompt: 'Why do more people use the AI summary than the AI search?',
            chart: newsChart({
                kind: 'grouped_bars',
                caption: 'Weekly users, last week and this week',
                items: [
                    { label: 'AI summary', before: 1200, value: 1640 },
                    { label: 'AI search', before: 980, value: 950 },
                ],
            }),
        },
        {
            id: 'week-traffic-sources',
            product: 'web_analytics',
            product_label: 'Web analytics',
            title: 'Newsletter visits doubled this week',
            summary: 'The newsletter now sends more visitors than paid search.',
            change: 100,
            tone: 'good',
            dive_prompt: 'Newsletter visits doubled this week. Which issues drove them, and do they convert?',
            chart: newsChart({
                kind: 'grouped_bars',
                caption: 'Visits by source, last week and this week',
                items: [
                    { label: 'Newsletter', before: 400, value: 800 },
                    { label: 'Organic search', before: 2500, value: 2800 },
                    { label: 'Paid search', before: 900, value: 740 },
                ],
            }),
        },
        {
            id: 'week-signups',
            product: 'product_analytics',
            product_label: 'Product analytics',
            title: 'Sign-ups rose for a fourth week in a row',
            summary: 'Each week brought more sign-ups than the last, mostly from team invites.',
            change: 9,
            tone: 'good',
            dive_prompt: 'Sign-ups rose for four weeks. Which channels drive the growth?',
            chart: newsChart({
                kind: 'line',
                caption: '',
                labels: NEWS_LABELS.slice(-7),
                values: [310, 335, 362, 371, 398, 420, 452],
            }),
        },
    ],
    briefs: NEWS_EDITION.briefs.slice(0, 1),
}
