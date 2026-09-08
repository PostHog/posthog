import { dayjs } from 'lib/dayjs'

import { backfillConditionFilters, backfillRangeDateFormat, backfillSamplingLabel } from './backfillConditions'

const MODEL_FILTER = { key: '$ai_model', value: 'gpt-5', operator: 'exact', type: 'event' }

describe('backfillConditions', () => {
    it.each([
        [undefined, '100% sampled'],
        [100, '100% sampled'],
        [50, '50% sampled'],
        [0.5, '0.5% sampled'],
        [0.04, '0.04% sampled'],
        [63.75, '63.8% sampled'],
        [99.95, '99.9% sampled'],
        [99.999, '99.9% sampled'],
    ])('renders rollout %s as %s', (rolloutPercentage: number | undefined, expected: string) => {
        expect(backfillSamplingLabel({ rollout_percentage: rolloutPercentage })).toBe(expected)
    })

    it('treats a condition set without properties as unfiltered', () => {
        expect(backfillConditionFilters({})).toEqual([])
    })

    it('carries a property filter through unchanged', () => {
        expect(backfillConditionFilters({ properties: [MODEL_FILTER] })).toEqual([MODEL_FILTER])
    })

    it.each([
        ['both bounds in the current year', '2026-08-31T00:00:00Z', '2026-09-07T00:00:00Z', 'MMM D'],
        ['a range crossing into the current year', '2025-12-28T00:00:00Z', '2026-01-03T00:00:00Z', 'MMM D, YYYY'],
        ['both bounds in a past year', '2025-03-01T00:00:00Z', '2025-03-08T00:00:00Z', 'MMM D, YYYY'],
    ])('formats %s', (_name: string, start: string, end: string, expected: string) => {
        expect(backfillRangeDateFormat(start, end, dayjs('2026-09-07T12:00:00Z'))).toBe(expected)
    })
})
