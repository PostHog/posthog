import { agentSpendTotals } from './agentUsageTotals'

describe('agentSpendTotals', () => {
    it.each([
        [
            'splits today, this month, and the whole window',
            [
                { day: '2026-09-28', cost_usd: 4 },
                { day: '2026-10-01', cost_usd: 1.5 },
                { day: '2026-10-02', cost_usd: 2 },
            ],
            '2026-10-02',
            { todayUsd: 2, monthUsd: 3.5, windowUsd: 7.5 },
        ],
        [
            'reads a day with a time part as that day',
            [{ day: '2026-10-02T00:00:00Z', cost_usd: 3 }],
            '2026-10-02',
            { todayUsd: 3, monthUsd: 3, windowUsd: 3 },
        ],
        ['returns zeros for no spend', [], '2026-10-02', { todayUsd: 0, monthUsd: 0, windowUsd: 0 }],
    ])('%s', (_name, days, todayIso, expected) => {
        expect(agentSpendTotals(days, todayIso)).toEqual(expected)
    })
})
