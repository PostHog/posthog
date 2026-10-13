import type { SignalReportListApi } from 'products/signals/frontend/generated/api.schemas'

import { reportTimelineExtras } from './ThreadReports'

describe('reportTimelineExtras', () => {
    it('places a report at the time this ticket linked to it, not at its last update', () => {
        const report = {
            id: 'report-1',
            created_at: '2026-01-01T00:00:00Z',
            source_linked_at: '2026-01-02T00:00:00Z',
            updated_at: '2026-03-01T00:00:00Z',
        } as SignalReportListApi

        expect(reportTimelineExtras([report]).map((extra) => extra.at)).toEqual(['2026-01-02T00:00:00Z'])
    })
})
