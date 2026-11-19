import type { ProductPushCampaignApi } from 'products/growth/frontend/generated/api.schemas'
import { makeReport } from 'products/signals/frontend/inbox/__mocks__/inboxMocks'
import type { HighlightItemApi } from 'products/today/frontend/generated/api.schemas'

import { type ProductPushSlot, forYouReportIds, forYouRows, productPushSlot } from './todayForYouRows'

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

const CAMPAIGN = { id: 'campaign-1', product_key: 'session_replay' } as ProductPushCampaignApi

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

    it.each([
        {
            name: 'joins the middle of the first rows without taking one',
            ids: ['a', 'b', 'c', 'd', 'e', 'f'],
            more: [] as string[],
            slot: 'visible' as ProductPushSlot,
            keys: ['a', 'b', 'c', 'push', 'd', 'e', 'f', 'risk-1'],
            limit: 6,
        },
        {
            name: 'leads the rows that show more adds',
            ids: ['a', 'b', 'c', 'd', 'e', 'f'],
            more: [] as string[],
            slot: 'expanded' as ProductPushSlot,
            keys: ['a', 'b', 'c', 'd', 'e', 'push', 'f', 'risk-1'],
            limit: 5,
        },
        {
            name: 'stays out when nothing is behind show more',
            ids: ['a'],
            more: [] as string[],
            slot: 'expanded' as ProductPushSlot,
            keys: ['a', 'risk-1'],
            limit: 2,
        },
        {
            name: 'leads the loaded reports when the first rows all fit',
            ids: ['a'],
            more: ['more'],
            slot: 'expanded' as ProductPushSlot,
            keys: ['a', 'risk-1', 'push', 'more'],
            limit: 2,
        },
    ])('the product push $name', ({ ids, more, slot, keys, limit }) => {
        const result = forYouRows({
            reports: ids.map((id) => makeReport({ id })),
            loadedMoreReports: more.map((id) => makeReport({ id })),
            highlights: [highlight('risk-1', 'risk')],
            doneHighlightKeys: [],
            reportStateOverrides: {},
            productPush: { campaign: CAMPAIGN, slot },
        })

        expect(result.rows.map((row) => (row.kind === 'product_push' ? 'push' : row.key))).toEqual(keys)
        expect(result.limit).toBe(limit)
    })

    it('never adds the product push to an empty list', () => {
        const { rows } = forYouRows({
            reports: [],
            loadedMoreReports: [],
            highlights: [],
            doneHighlightKeys: [],
            reportStateOverrides: {},
            productPush: { campaign: CAMPAIGN, slot: 'visible' },
        })

        expect(rows).toEqual([])
    })

    it('puts the product push in both slots across days and keeps one slot per day', () => {
        const days = Array.from({ length: 30 }, (_, index) => `2026-11-${String(index + 1).padStart(2, '0')}`)

        const slots = days.map((day) => productPushSlot('campaign-1', 'user-1', day))

        expect(new Set(slots)).toEqual(new Set(['visible', 'expanded']))
        expect(days.map((day) => productPushSlot('campaign-1', 'user-1', day))).toEqual(slots)
    })
})
