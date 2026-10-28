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
    it.each([
        { ids: [], visible: 2, done: ['risk-1'] },
        { ids: ['a', 'b'], visible: 4, done: ['b', 'risk-1'] },
        { ids: ['a', 'b', 'c', 'd', 'e'], visible: 5, done: ['b', 'risk-1'] },
        { ids: ['a', 'b', 'c', 'd', 'e', 'f'], visible: 5, done: ['b', 'risk-1'] },
    ])('keeps report order and highlights with $ids and a visible limit of $visible', ({ ids, visible, done }) => {
        const reports = ids.map((id) => makeReport({ id }))
        const { rows, limit } = forYouRows({
            reports,
            loadedMoreReports: [makeReport({ id: 'more' })],
            highlights: [highlight('risk-1', 'risk'), highlight('opportunity-1', 'opportunity')],
            doneHighlightKeys: ['risk-1'],
            reportStateOverrides: { b: 'resolved' },
        })

        expect(limit).toBe(visible)
        expect(rows.map((row) => row.key)).toEqual([...ids, 'risk-1', 'opportunity-1', 'more'])
        expect(rows.filter((row) => row.done).map((row) => row.key)).toEqual(done)
        expect(forYouReportIds(rows)).toEqual([...ids, 'more'])
    })
})
