import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType } from '~/types'

import { HideWeekendsMigrationOutcome, hideWeekendsMigrationOutcome } from './HideWeekendsDeprecationNotice'

function trendsQuery(overrides: Partial<TrendsQuery> = {}): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        trendsFilter: { hideWeekends: true, ...overrides.trendsFilter },
        ...overrides,
    }
}

describe('hideWeekendsMigrationOutcome', () => {
    it.each<[string, Partial<TrendsQuery>, HideWeekendsMigrationOutcome]>([
        // switch: day-interval time series without cross-day aggregation is result-identical under daysOfWeek
        ['day interval line graph', { interval: 'day' }, 'switch'],
        ['unset interval defaults to day', {}, 'switch'],
        ['bar display', { trendsFilter: { display: ChartDisplayType.ActionsBar } }, 'switch'],
        // remove: hideWeekends never drops buckets on these shapes, so the key is dead weight
        ['week interval', { interval: 'week' }, 'remove'],
        ['hour interval', { interval: 'hour' }, 'remove'],
        ['bold number display', { trendsFilter: { display: ChartDisplayType.BoldNumber } }, 'remove'],
        ['pie display', { trendsFilter: { display: ChartDisplayType.ActionsPie } }, 'remove'],
        // interval exemption wins over series math: hourly WAU is still a no-op
        [
            'hour interval with WAU math',
            {
                interval: 'hour',
                series: [{ kind: NodeKind.EventsNode, math: BaseMathType.WeeklyActiveUsers }],
            },
            'remove',
        ],
        // keep: weekend events still feed the visible values, so a rewrite would change results
        [
            'weekly active users math',
            { series: [{ kind: NodeKind.EventsNode, math: BaseMathType.WeeklyActiveUsers }] },
            'keep',
        ],
        [
            'monthly active users on a second series',
            {
                series: [
                    { kind: NodeKind.EventsNode },
                    { kind: NodeKind.EventsNode, math: BaseMathType.MonthlyActiveUsers },
                ],
            },
            'keep',
        ],
        ['cumulative display', { trendsFilter: { display: ChartDisplayType.ActionsLineGraphCumulative } }, 'keep'],
        // second interval: the runner drops weekend buckets there, but daysOfWeek would not
        ['second interval', { interval: 'second' }, 'keep'],
        ['smoothing over 7 days', { trendsFilter: { smoothingIntervals: 7 } }, 'keep'],
        ['days of week already set', { dateRange: { daysOfWeek: [1, 2, 3] } }, 'keep'],
        // smoothingIntervals of 1 is the "off" value the UI persists
        ['smoothing of 1 is off', { trendsFilter: { smoothingIntervals: 1 } }, 'switch'],
    ])('%s -> %s', (_name, overrides, expected) => {
        expect(hideWeekendsMigrationOutcome(trendsQuery(overrides))).toBe(expected)
    })
})
