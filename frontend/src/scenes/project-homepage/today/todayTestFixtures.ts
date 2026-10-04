import type { SignalViewApi } from 'products/today/frontend/generated/api.schemas'

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
