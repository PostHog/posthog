import { makeReport } from 'products/signals/frontend/inbox/__mocks__/inboxMocks'
import type { HighlightItemApi } from 'products/today/frontend/generated/api.schemas'

import { forYouReportIds, forYouRows } from './todayForYouRows'

function highlight(key: string, label: HighlightItemApi['label']): HighlightItemApi {
    return {
        key,
        label,
        priority: label === 'risk' ? 'P2' : 'P4',
        title: key,
        detail: '',
        url: null,
        series: null,
        score: 1,
        source: 'alerts',
    }
}

describe('forYouRows', () => {
    it('keeps the server order, puts reports before highlights and more reports last, and steps through reports in list order', () => {
        const reports = ['a', 'b', 'c', 'd', 'e', 'f'].map((id) => makeReport({ id }))
        const { rows, limit } = forYouRows({
            reports,
            loadedMoreReports: [makeReport({ id: 'more' })],
            highlights: [highlight('risk-1', 'risk'), highlight('opportunity-1', 'opportunity')],
            doneHighlightKeys: ['risk-1'],
            reportStateOverrides: { b: 'resolved' },
        })

        expect(limit).toBe(5)
        expect(rows.map((row) => row.key)).toEqual(['a', 'b', 'c', 'd', 'e', 'f', 'risk-1', 'opportunity-1', 'more'])
        expect(rows.filter((row) => row.done).map((row) => row.key)).toEqual(['b', 'risk-1'])
        expect(forYouReportIds(rows)).toEqual(['a', 'b', 'c', 'd', 'e', 'f', 'more'])
    })
})
