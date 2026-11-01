import { dayjs } from 'lib/dayjs'

import type { AICreditHistoryEntryApi, AISpendResponseApi } from 'products/billing/frontend/generated/api.schemas'

import { reloadedSince, spendLimitOutlook, summarizeSpend } from './aiSpend'

const SPEND: AISpendResponseApi = {
    balance_usd: '60.000000',
    period_start: '2026-10-18',
    period_end: '2026-11-18',
    spend_usd: '100.000000',
    free_usd: '5.000000',
    products: [
        { product: 'chat', name: 'Chat', spend_usd: '100.000000', free_usd: '0.000000' },
        { product: 'free_only', name: 'Free only', spend_usd: '0.000000', free_usd: '5.000000' },
    ],
    days: [
        { date: '2026-10-18', spend_usd: { chat: '20.000000' } },
        { date: '2026-10-19', spend_usd: { chat: '50.000000', free_only: '0.000000' } },
        { date: '2026-10-20', spend_usd: { chat: '10.000000' } },
        { date: '2026-10-21', spend_usd: { chat: '20.000000' } },
    ],
}

// Five days have started: Oct 18 to Oct 22.
const NOW = dayjs.utc('2026-10-22T06:00:00Z')

function entry(kind: AICreditHistoryEntryApi['kind'], createdAt: string, amountUsd: string): AICreditHistoryEntryApi {
    return {
        created_at: createdAt,
        kind,
        amount_usd: amountUsd,
        tax_usd: '0.00',
        total_usd: amountUsd,
        status: 'added',
        receipt_url: null,
    }
}

describe('aiSpend', () => {
    it('averages over the days started so far and compares with the whole previous period', () => {
        const previous = { ...SPEND, period_start: '2026-09-18', period_end: '2026-10-18', spend_usd: '300.000000' }

        const summary = summarizeSpend(SPEND, previous, NOW)

        expect(summary.dailyAverageUsd).toEqual(20)
        expect(summary.previousDailyAverageUsd).toEqual(10)
        expect(summary.changeFromPrevious).toEqual(1)
        expect(summary.busiestDay?.date.format('YYYY-MM-DD')).toEqual('2026-10-19')
        expect(summary.productsWithSpend).toEqual(1)
    })

    it.each([
        ['reaches it this period', 150, { reached: false, date: '2026-10-24' }],
        ['stays under it this period', 1000, { reached: false, date: null }],
        ['has reached it', 100, { reached: true }],
    ])('says when spend %s', (_, limitUsd, expected) => {
        const outlook = spendLimitOutlook(summarizeSpend(SPEND, null, NOW), limitUsd, NOW)

        expect(outlook.reached ? outlook : { ...outlook, date: outlook.date?.format('YYYY-MM-DD') ?? null }).toEqual(
            expected
        )
    })

    it.each([
        ['counts every reload in the period when the history is complete', false, '2026-10-20T00:00:00Z', 175],
        ['knows nothing when older entries may still be in the period', true, '2026-10-20T00:00:00Z', null],
        ['leaves out reloads from before the period', true, '2026-10-10T00:00:00Z', 100],
    ])('%s', (_, hasMore, oldestAt, expected) => {
        const history = {
            has_more: hasMore,
            results: [
                entry('automatic_reload', '2026-10-30T00:00:00Z', '60.00'),
                entry('purchase', '2026-10-25T00:00:00Z', '200.00'),
                entry('automatic_reload', '2026-10-21T00:00:00Z', '40.00'),
                entry('automatic_reload', oldestAt, '75.00'),
            ],
        }

        expect(reloadedSince(history, SPEND.period_start)).toEqual(expected)
    })
})
