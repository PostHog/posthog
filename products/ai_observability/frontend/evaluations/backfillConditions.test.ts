import { dayjs } from 'lib/dayjs'

import type { EvaluationBackfillApi } from '../generated/api.schemas'
import {
    backfillCoveredCount,
    backfillLateArrivalCount,
    backfillRangeDateFormat,
    backfillSamplingLabel,
    backfillTotalCount,
} from './backfillConditions'

function backfill(overrides: Partial<EvaluationBackfillApi> = {}): EvaluationBackfillApi {
    return {
        status: 'completed',
        total_count: 8,
        dispatched_count: 2,
        skipped_count: 1,
        remaining_count: 0,
        ...overrides,
    } as EvaluationBackfillApi
}

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

    it.each([
        ['both bounds in the current year', '2026-08-31T00:00:00Z', '2026-09-07T00:00:00Z', 'MMM D'],
        ['a range crossing into the current year', '2025-12-28T00:00:00Z', '2026-01-03T00:00:00Z', 'MMM D, YYYY'],
        ['both bounds in a past year', '2025-03-01T00:00:00Z', '2025-03-08T00:00:00Z', 'MMM D, YYYY'],
    ])('formats %s', (_name: string, start: string, end: string, expected: string) => {
        expect(backfillRangeDateFormat(start, end, dayjs('2026-09-07T12:00:00Z'))).toBe(expected)
    })
})

describe('backfillCoveredCount', () => {
    it.each([
        ['a finished run counts what the window still owed', {}, 8],
        ['a finished run that left work counts the rest', { remaining_count: 3 }, 5],
        ['an unmeasured run counts what the walk handled', { remaining_count: null }, 3],
        ['a running one counts what the walk handled', { status: 'running' as const, remaining_count: null }, 3],
        [
            'a remainder above the total cannot go negative',
            { total_count: 1, dispatched_count: 0, skipped_count: 0, remaining_count: 2 },
            0,
        ],
        ['a run that handled more than its estimate counts all of it', { dispatched_count: 10, skipped_count: 0 }, 10],
    ])('%s', (_case, overrides, expected) => {
        expect(backfillCoveredCount(backfill(overrides))).toEqual(expected)
    })

    it.each([
        ['the estimate stands while the walk handled less', {}, 8, 0],
        ['the total rises to what the walk found', { dispatched_count: 10, skipped_count: 0 }, 10, 2],
    ])('%s', (_case, overrides, total, late) => {
        expect(backfillTotalCount(backfill(overrides))).toEqual(total)
        expect(backfillLateArrivalCount(backfill(overrides))).toEqual(late)
    })
})
