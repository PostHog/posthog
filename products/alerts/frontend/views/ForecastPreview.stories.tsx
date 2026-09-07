import type { Meta, StoryObj } from '@storybook/react'

import { ForecastConditionType, ForecastEngineType, ForecastTargetDirection } from '~/queries/schema/schema-general'

import type { ForecastSimulateResponseApi } from '../generated/api.schemas'
import { ForecastPreview } from './ForecastPreview'

const HISTORY_DATES = [
    '2026-08-25',
    '2026-08-26',
    '2026-08-27',
    '2026-08-28',
    '2026-08-29',
    '2026-08-30',
    '2026-08-31',
    '2026-09-01',
    '2026-09-02',
    '2026-09-03',
    '2026-09-04',
    '2026-09-05',
    '2026-09-06',
    '2026-09-07',
]
const HISTORY_VALUES = [56, 58, 61, 64, 60, 59, 66, 69, 72, 74, 71, 76, 79, 82]
const FORECAST_DATES = [
    '2026-09-08',
    '2026-09-09',
    '2026-09-10',
    '2026-09-11',
    '2026-09-12',
    '2026-09-13',
    '2026-09-14',
]
const FORECAST_VALUES = [84, 87, 90, 94, 97, 101, 104]

const BASE_RESULT: ForecastSimulateResponseApi = {
    data: HISTORY_VALUES,
    dates: HISTORY_DATES,
    interval: 'day',
    forecast_dates: FORECAST_DATES,
    forecast_yhat: FORECAST_VALUES,
    forecast_lower: [78, 80, 83, 85, 87, 90, 92],
    forecast_upper: [91, 94, 98, 103, 107, 112, 117],
    target_projection: null,
}

const meta: Meta<typeof ForecastPreview> = {
    title: 'Products/Alerts/Forecast preview',
    component: ForecastPreview,
    parameters: {
        layout: 'fullscreen',
        testOptions: { waitForSelector: '[data-attr="forecast-preview-chart"]' },
    },
    decorators: [
        (Story): JSX.Element => (
            <div className="min-h-screen bg-bg-primary p-4">
                <div className="max-w-xl border rounded bg-surface-primary p-4">
                    <Story />
                </div>
            </div>
        ),
    ],
}

export default meta

type Story = StoryObj<typeof meta>

export const UpcomingThresholdBreach: Story = {
    args: {
        result: BASE_RESULT,
        thresholdBounds: { upper: 95 },
        forecastConfig: {
            type: 'ForecastConfig',
            engine: ForecastEngineType.PROPHET,
            condition: ForecastConditionType.FUTURE_BREACH,
            horizon: 7,
        },
    },
}

export const TargetByDate: Story = {
    args: {
        result: {
            ...BASE_RESULT,
            target_projection: {
                predicted: 101,
                target: 110,
                target_date: '2026-09-13',
                evaluated_date: '2026-09-13',
                misses_target: true,
            },
        },
        thresholdBounds: null,
        forecastConfig: {
            type: 'ForecastConfig',
            engine: ForecastEngineType.PROPHET,
            condition: ForecastConditionType.TARGET_BY_DATE,
            target: 110,
            target_direction: ForecastTargetDirection.AT_LEAST,
            target_date: '2026-09-13',
        },
    },
}

export const TargetByDateNarrowDark: Story = {
    ...TargetByDate,
    globals: { theme: 'dark' },
    parameters: { testOptions: { skipLightMode: true } },
    decorators: [
        (Story): JSX.Element => (
            <div className="w-[360px] border rounded bg-surface-primary p-3">
                <Story />
            </div>
        ),
    ],
}
