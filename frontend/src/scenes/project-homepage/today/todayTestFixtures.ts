import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'
import { SignalReport, SignalReportStatus } from 'products/signals/frontend/inbox/types'

export function signal(overrides: Partial<SignalNodeApi>): SignalNodeApi {
    return {
        signal_id: 'signal-1',
        content: '',
        source_product: 'signals_scout',
        source_type: 'cross_source_issue',
        source_id: 'source-1',
        weight: 1,
        timestamp: '2026-10-01T10:00:00Z',
        extra: {} as SignalNodeApi['extra'],
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
