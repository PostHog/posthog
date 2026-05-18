import type { Meta, StoryObj } from '@storybook/react'

import { dayjs, type Dayjs } from 'lib/dayjs'

import {
    AlertCalculationInterval,
    AlertConditionType,
    AlertState,
    InsightThresholdType,
} from '~/queries/schema/schema-general'
import type { QueryBasedInsightModel } from '~/types'
import type { UserBasicType } from '~/types'

import { CHART_CHECKS_LIMIT } from '../alertLogic'
import type { AlertType } from '../types'
import { AlertHistoryChart, type AlertHistoryChartPoint } from './AlertHistoryChart'

const STORY_USER: UserBasicType = {
    id: 1,
    uuid: '00000000-0000-0000-0000-000000000001',
    distinct_id: 'story',
    first_name: 'Story',
    email: 'story@example.com',
}

const EMPTY_INSIGHT = {} as QueryBasedInsightModel

function buildStoryAlert(overrides: Partial<AlertType> & Pick<AlertType, 'threshold'>): AlertType {
    return {
        id: '11111111-1111-1111-1111-111111111111',
        name: 'Storybook alert',
        condition: { type: AlertConditionType.ABSOLUTE_VALUE },
        enabled: true,
        insight: EMPTY_INSIGHT,
        config: { type: 'TrendsAlertConfig', series_index: 0 },
        subscribed_users: [],
        created_by: STORY_USER,
        created_at: dayjs().toISOString(),
        state: AlertState.NOT_FIRING,
        last_notified_at: dayjs().toISOString(),
        last_checked_at: dayjs().toISOString(),
        checks: [],
        calculation_interval: AlertCalculationInterval.DAILY,
        detector_config: null,
        ...overrides,
    }
}

function makePoints(count: number, seed = 0): AlertHistoryChartPoint[] {
    return Array.from({ length: count }, (_, i) => ({
        value: 45 + Math.sin((i + seed) / 2.5) * 22 + (i % 5) * 4 + (i === 12 ? 35 : 0),
        label: dayjs()
            .subtract(count - 1 - i, 'hour')
            .format('MMM D, HH:mm'),
    }))
}

/** X-axis labels that match how checks land for daily / weekly / monthly evaluation. */
function makePointsForEvaluationInterval(
    count: number,
    unit: 'day' | 'week' | 'month',
    labelFormat: string,
    seed = 0
): AlertHistoryChartPoint[] {
    return Array.from({ length: count }, (_, i) => ({
        value: 45 + Math.sin((i + seed) / 2.5) * 22 + (i % 5) * 4 + (i === Math.floor(count / 2) ? 35 : 0),
        label: dayjs()
            .subtract(count - 1 - i, unit)
            .format(labelFormat),
    }))
}

function minutesSinceMidnight(t: Dayjs): number {
    return t.hour() * 60 + t.minute()
}

function parseHHMMToMinutes(s: string): number {
    const [h, m] = s.split(':').map(Number)
    return h * 60 + m
}

/** Half-open [start, end) in project local time; supports overnight (e.g. 22:00–07:00). */
function isInBlockedQuietWindow(t: Dayjs, start: string, end: string): boolean {
    const now = minutesSinceMidnight(t)
    const s = parseHHMMToMinutes(start)
    const e = parseHHMMToMinutes(end)
    if (s < e) {
        return now >= s && now < e
    }
    if (s > e) {
        return now >= s || now < e
    }
    return false
}

function synthValue(i: number, count: number, seed: number): number {
    return 45 + Math.sin((i + seed) / 2.5) * 22 + (i % 5) * 4 + (i === Math.floor(count / 2) ? 35 : 0)
}

/** Hourly checks only on weekdays (no Sat/Sun), newest on the right. */
function makeHourlyPointsSkippingWeekends(pointCount: number, seed = 0): AlertHistoryChartPoint[] {
    const rev: { label: string }[] = []
    let t = dayjs().startOf('hour')
    while (rev.length < pointCount) {
        const dow = t.day()
        if (dow !== 0 && dow !== 6) {
            rev.push({ label: t.format('MMM D, HH:mm') })
        }
        t = t.subtract(1, 'hour')
    }
    return rev.reverse().map((p, i) => ({
        label: p.label,
        value: synthValue(i, pointCount, seed),
    }))
}

/** One check per weekday only (daily + skip weekends). */
function makeDailyPointsSkippingWeekends(dayCount: number, seed = 0): AlertHistoryChartPoint[] {
    const rev: { label: string }[] = []
    let t = dayjs().startOf('day')
    while (rev.length < dayCount) {
        const dow = t.day()
        if (dow !== 0 && dow !== 6) {
            rev.push({ label: t.format('ddd, MMM D') })
        }
        t = t.subtract(1, 'day')
    }
    return rev.reverse().map((p, i) => ({
        label: p.label,
        value: synthValue(i, dayCount, seed),
    }))
}

/** Hourly checks outside quiet hours (e.g. overnight block defers runs → uneven spacing on the axis). */
function makeHourlyPointsOutsideQuietHours(
    pointCount: number,
    blocked: { start: string; end: string },
    seed = 0
): AlertHistoryChartPoint[] {
    const rev: { label: string }[] = []
    let t = dayjs().startOf('hour')
    while (rev.length < pointCount) {
        if (!isInBlockedQuietWindow(t, blocked.start, blocked.end)) {
            rev.push({ label: t.format('MMM D, HH:mm') })
        }
        t = t.subtract(1, 'hour')
    }
    return rev.reverse().map((p, i) => ({
        label: p.label,
        value: synthValue(i, pointCount, seed),
    }))
}

/** Hourly checks on weekdays only and outside quiet hours. */
function makeHourlyPointsWeekdaysOutsideQuietHours(
    pointCount: number,
    blocked: { start: string; end: string },
    seed = 0
): AlertHistoryChartPoint[] {
    const rev: { label: string }[] = []
    let t = dayjs().startOf('hour')
    while (rev.length < pointCount) {
        const dow = t.day()
        if (dow !== 0 && dow !== 6 && !isInBlockedQuietWindow(t, blocked.start, blocked.end)) {
            rev.push({ label: t.format('MMM D, HH:mm') })
        }
        t = t.subtract(1, 'hour')
    }
    return rev.reverse().map((p, i) => ({
        label: p.label,
        value: synthValue(i, pointCount, seed),
    }))
}

/**
 * Stamp each point with `firedAtTime` derived from the thresholds that were in effect at evaluation time.
 * Use this for stories that demonstrate the real historical-firing signal (red dots), independent of
 * whatever thresholds the story's alert is currently configured with.
 */
function withHistoricalFirings(
    points: AlertHistoryChartPoint[],
    atTimeBounds: { lower?: number | null; upper?: number | null }
): AlertHistoryChartPoint[] {
    const lower = atTimeBounds.lower ?? null
    const upper = atTimeBounds.upper ?? null
    return points.map((p) => {
        const firedAtTime = (upper != null && p.value > upper) || (lower != null && p.value < lower)
        return { ...p, firedAtTime }
    })
}

const meta: Meta<typeof AlertHistoryChart> = {
    title: 'Components/Alerts/Alert history chart',
    component: AlertHistoryChart,
    args: {
        historyLimit: CHART_CHECKS_LIMIT,
        checksTotal: null,
    },
    decorators: [
        (Story): JSX.Element => (
            <div className="max-w-3xl rounded border p-4 bg-bg-primary">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof AlertHistoryChart>

const defaultPoints = makePoints(20)

export const Default: Story = {
    args: {
        points: defaultPoints,
        valueLabel: 'Value',
        chartPlotsAnomalyScore: false,
        alert: buildStoryAlert({
            threshold: {
                configuration: {
                    type: InsightThresholdType.ABSOLUTE,
                    bounds: { lower: 40, upper: 85 },
                },
            },
        }),
    },
}

/** Caption when total checks exceed the chart window (see `historyLimit`). */
export const MoreChecksThanChartWindow: Story = {
    args: {
        ...Default.args,
        checksTotal: 240,
    },
}

/** One check per calendar day (daily evaluation). */
export const DailyEvaluationTimeAxis: Story = {
    args: {
        ...Default.args,
        points: makePointsForEvaluationInterval(14, 'day', 'ddd, MMM D'),
        alert: buildStoryAlert({
            calculation_interval: AlertCalculationInterval.DAILY,
            threshold: {
                configuration: {
                    type: InsightThresholdType.ABSOLUTE,
                    bounds: { lower: 40, upper: 85 },
                },
            },
        }),
    },
}

/** One check per week (weekly evaluation). */
export const WeeklyEvaluationTimeAxis: Story = {
    args: {
        ...Default.args,
        points: makePointsForEvaluationInterval(10, 'week', '[Week of] MMM D'),
        alert: buildStoryAlert({
            calculation_interval: AlertCalculationInterval.WEEKLY,
            threshold: {
                configuration: {
                    type: InsightThresholdType.ABSOLUTE,
                    bounds: { lower: 40, upper: 85 },
                },
            },
        }),
    },
}

/** One check per month (monthly evaluation). */
export const MonthlyEvaluationTimeAxis: Story = {
    args: {
        ...Default.args,
        points: makePointsForEvaluationInterval(8, 'month', 'MMM YYYY'),
        alert: buildStoryAlert({
            calculation_interval: AlertCalculationInterval.MONTHLY,
            threshold: {
                configuration: {
                    type: InsightThresholdType.ABSOLUTE,
                    bounds: { lower: 40, upper: 85 },
                },
            },
        }),
    },
}

const DEFAULT_QUIET_HOURS = { start: '22:00', end: '07:00' }

/** Hourly checks only land on weekdays when `skip_weekend` is set (gaps across Sat/Sun). */
export const SkipWeekendsHourly: Story = {
    args: {
        ...Default.args,
        points: makeHourlyPointsSkippingWeekends(28, 1),
        alert: buildStoryAlert({
            calculation_interval: AlertCalculationInterval.HOURLY,
            skip_weekend: true,
            threshold: {
                configuration: {
                    type: InsightThresholdType.ABSOLUTE,
                    bounds: { lower: 40, upper: 85 },
                },
            },
        }),
    },
}

/** Daily checks only on weekdays (skip weekend). */
export const SkipWeekendsDaily: Story = {
    args: {
        ...Default.args,
        points: makeDailyPointsSkippingWeekends(14, 2),
        alert: buildStoryAlert({
            calculation_interval: AlertCalculationInterval.DAILY,
            skip_weekend: true,
            threshold: {
                configuration: {
                    type: InsightThresholdType.ABSOLUTE,
                    bounds: { lower: 40, upper: 85 },
                },
            },
        }),
    },
}

/** Quiet hours defer checks — hourly timeline has uneven gaps (e.g. nothing overnight). */
export const QuietHoursHourly: Story = {
    args: {
        ...Default.args,
        points: makeHourlyPointsOutsideQuietHours(32, DEFAULT_QUIET_HOURS, 3),
        alert: buildStoryAlert({
            calculation_interval: AlertCalculationInterval.HOURLY,
            schedule_restriction: { blocked_windows: [DEFAULT_QUIET_HOURS] },
            threshold: {
                configuration: {
                    type: InsightThresholdType.ABSOLUTE,
                    bounds: { lower: 40, upper: 85 },
                },
            },
        }),
    },
}

/** Both skip weekend and quiet hours (hourly). */
export const SkipWeekendsAndQuietHoursHourly: Story = {
    args: {
        ...Default.args,
        points: makeHourlyPointsWeekdaysOutsideQuietHours(36, DEFAULT_QUIET_HOURS, 4),
        alert: buildStoryAlert({
            calculation_interval: AlertCalculationInterval.HOURLY,
            skip_weekend: true,
            schedule_restriction: { blocked_windows: [DEFAULT_QUIET_HOURS] },
            threshold: {
                configuration: {
                    type: InsightThresholdType.ABSOLUTE,
                    bounds: { lower: 40, upper: 85 },
                },
            },
        }),
    },
}

export const PercentageThresholds: Story = {
    args: {
        points: makePoints(18, 2).map((p) => ({ ...p, value: (p.value - 40) / 100 })),
        valueLabel: 'Relative change',
        chartPlotsAnomalyScore: false,
        alert: buildStoryAlert({
            threshold: {
                configuration: {
                    type: InsightThresholdType.PERCENTAGE,
                    bounds: { lower: -0.3, upper: 0.35 },
                },
            },
        }),
    },
}

export const AnomalyProbabilityCutoff: Story = {
    args: {
        points: Array.from({ length: 16 }, (_, i) => ({
            value: Math.min(0.99, 0.15 + i * 0.045 + (i === 10 ? 0.25 : 0)),
            label: dayjs()
                .subtract(16 - 1 - i, 'hour')
                .format('MMM D, HH:mm'),
        })),
        valueLabel: 'Anomaly score',
        chartPlotsAnomalyScore: true,
        alert: buildStoryAlert({
            detector_config: { type: 'zscore', threshold: 0.88, window: 30 },
            threshold: {
                configuration: { type: InsightThresholdType.ABSOLUTE, bounds: {} },
            },
        }),
    },
}

/**
 * Upper bound tightened, lower bound widened.
 * Red dots above the upper line fired at the time and still would.
 * Red dots below the lower line fired at the time but wouldn't under current config (widened).
 * Orange dots between old and new upper bound would now fire but didn't then (tightened).
 */
export const MixedThresholdChange: Story = {
    args: {
        ...Default.args,
        points: withHistoricalFirings(makePoints(30, 11), { lower: 38, upper: 80 }),
        alert: buildStoryAlert({
            threshold: {
                configuration: {
                    type: InsightThresholdType.ABSOLUTE,
                    bounds: { lower: 25, upper: 62 },
                },
            },
        }),
    },
}
