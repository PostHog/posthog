import { SignalReport, SignalReportStatus } from 'products/signals/frontend/inbox/types'
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

export function report(overrides: Partial<SignalReport>): SignalReport {
    return {
        id: 'report-1',
        title: 'fix(checkout): keep the billing address',
        summary: 'Lead.',
        status: SignalReportStatus.READY,
        signal_count: 1,
        created_at: '2026-10-01T10:00:00Z',
        updated_at: '2026-10-01T10:00:00Z',
        ...overrides,
    } as SignalReport
}
