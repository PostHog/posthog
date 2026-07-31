import { NodeKind, type DateRange } from '~/queries/schema/schema-general'
import { FunnelVizType } from '~/types'

import {
    computeDaysOfWeekUpdate,
    getExcludedDaysOfWeek,
    invertDaysOfWeek,
    querySupportsDaysOfWeek,
    type IsoDayOfWeek,
} from './daysOfWeekFilterUtils'

describe('daysOfWeekFilterUtils', () => {
    it.each([
        [[], []],
        [[1, 2, 3, 4, 5, 6, 7], []],
        [
            [6, 7],
            [1, 2, 3, 4, 5],
        ],
        [
            [1, 2, 3, 4, 5],
            [6, 7],
        ],
        [[3], [1, 2, 4, 5, 6, 7]],
    ] as [IsoDayOfWeek[], IsoDayOfWeek[]][])('inverts %j to %j', (days, expected) => {
        expect(invertDaysOfWeek(days)).toEqual(expected)
    })

    it.each([
        [undefined, []],
        [null, []],
        [{ daysOfWeek: null }, []],
        [{ daysOfWeek: [] }, []],
        [{ daysOfWeek: [6, 7] }, [1, 2, 3, 4, 5]],
        [{ daysOfWeek: [5, 1, 3] }, [2, 4, 6, 7]],
    ] as [DateRange | null | undefined, IsoDayOfWeek[]][])(
        'reads excluded days from dateRange %j as %j',
        (dateRange, expected) => {
            expect(getExcludedDaysOfWeek(dateRange)).toEqual(expected)
        }
    )

    it.each([
        [[], null],
        [[1, 2, 3, 4, 5, 6, 7], null],
        [
            [6, 7],
            [1, 2, 3, 4, 5],
        ],
        [
            [1, 2, 3, 4, 5],
            [6, 7],
        ],
    ] as [IsoDayOfWeek[], number[] | null][])(
        'computes a daysOfWeek update excluding %j as %j, normalizing none/all excluded to null',
        (excludedDays, expectedDaysOfWeek) => {
            const update = computeDaysOfWeekUpdate(excludedDays, { date_from: '-7d' })
            expect(update.dateRange?.daysOfWeek ?? null).toEqual(expectedDaysOfWeek)
        }
    )

    it('preserves the rest of the dateRange when computing an update', () => {
        const update = computeDaysOfWeekUpdate([6, 7], { date_from: '-7d', date_to: null })
        expect(update.dateRange).toEqual({ date_from: '-7d', date_to: null, daysOfWeek: [1, 2, 3, 4, 5] })
    })

    it.each([
        [null, false],
        [undefined, false],
        [{ kind: NodeKind.TrendsQuery }, true],
        [{ kind: NodeKind.StickinessQuery }, true],
        [{ kind: NodeKind.LifecycleQuery }, true],
        [{ kind: NodeKind.FunnelsQuery }, false],
        [{ kind: NodeKind.FunnelsQuery, funnelsFilter: { funnelVizType: FunnelVizType.Steps } }, false],
        [{ kind: NodeKind.FunnelsQuery, funnelsFilter: { funnelVizType: FunnelVizType.TimeToConvert } }, false],
        [{ kind: NodeKind.FunnelsQuery, funnelsFilter: { funnelVizType: FunnelVizType.Trends } }, true],
        [{ kind: NodeKind.RetentionQuery }, false],
        [{ kind: NodeKind.PathsQuery }, false],
    ] as [Record<string, any> | null | undefined, boolean][])(
        'querySupportsDaysOfWeek(%j) → %s',
        (querySource, expected) => {
            expect(querySupportsDaysOfWeek(querySource)).toBe(expected)
        }
    )
})
