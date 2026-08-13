import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import {
    AlertCalculationInterval,
    AlertConditionType,
    AlertState,
    InsightThresholdType,
} from '~/queries/schema/schema-general'
import type { QueryBasedInsightModel } from '~/types'
import type { UserBasicType } from '~/types'

import { CHART_CHECKS_LIMIT } from '../logic/alertLogic'
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
    title: 'Products/Alerts/Alert history chart',
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
export const TruncatedHistory: Story = {
    args: {
        ...Default.args,
        checksTotal: 240,
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
export const ThresholdChanged: Story = {
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
