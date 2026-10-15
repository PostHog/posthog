import type {
    BriefingApi,
    HighlightItemApi,
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

export function makeBriefing(overrides: Partial<BriefingApi> = {}): BriefingApi {
    return {
        id: 'briefing-1',
        local_day: '2026-09-30',
        headline: 'One report needs your input',
        paragraphs: [[{ text: 'Signup form rejects emails', item_key: 'report:a', highlight: true }]],
        items: [
            {
                key: 'report:a',
                title: 'Signup form rejects emails',
                label: 'Signup form rejects emails',
                signal: 'P1, waits for you',
                url: '/project/1/inbox/reports/a',
                rank: 1,
                group: 'report',
                source: 'self_driving',
                reason: 'waiting_for_you',
                state: 'open',
                source_product: null,
                report: null,
            },
        ],
        more_reports_count: 0,
        open_reports_count: 0,
        refresh_at: '2026-10-01T06:00:00Z',
        status: 'ready',
        writer: 'agent',
        created_at: '2026-09-30T06:00:00Z',
        ready_at: '2026-09-30T06:00:20Z',
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
