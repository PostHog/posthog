import type { Meta, StoryObj } from '@storybook/react'

import { DetectorConfig } from '~/queries/schema/schema-general'

import type { AlertSimulationResult } from '../types'
import { SimulationSummary } from './SimulationSummary'

const DATES = Array.from({ length: 14 }, (_, i) => `2026-06-${String(i + 1).padStart(2, '0')}`)
const VALUES = [42, 48, 51, 47, 90, 53, 55, 60, 120, 58, 54, 57, 95, 61]
const SCORES = [0.1, 0.15, 0.2, 0.12, 0.82, 0.18, 0.22, 0.3, 0.94, 0.25, 0.2, 0.24, 0.86, 0.28]
const TRIGGERED = [4, 8, 12]

// getThreshold reads `threshold` off any non-ensemble/threshold detector.
const DETECTOR_CONFIG = { type: 'zscore', threshold: 0.5 } as unknown as DetectorConfig

const SINGLE_RESULT: AlertSimulationResult = {
    data: VALUES,
    dates: DATES,
    scores: SCORES,
    triggered_indices: TRIGGERED,
    triggered_dates: TRIGGERED.map((i) => DATES[i]),
    interval: 'day',
    total_points: VALUES.length,
    anomaly_count: TRIGGERED.length,
}

const SUB_SCORES_RESULT: AlertSimulationResult = {
    ...SINGLE_RESULT,
    sub_detector_scores: [
        { type: 'z-score', scores: SCORES },
        { type: 'seasonality', scores: SCORES.map((s) => Math.max(0, s - 0.15)) },
        { type: 'trend', scores: SCORES.map((s) => Math.min(1, s + 0.1)) },
    ],
}

// 45 days of a weekly pattern. The first 30 points have too little history to forecast, and two later
// points land outside the forecast range.
const FORECAST_DATES = Array.from({ length: 45 }, (_, i) => `2026-05-${String((i % 31) + 1).padStart(2, '0')}`).map(
    (date, i) => (i < 31 ? date : `2026-06-${String(i - 30).padStart(2, '0')}`)
)
const FORECAST_EXPECTED = FORECAST_DATES.map((_, i) => 100 + (i % 7 >= 5 ? -30 : 0) + i)
const FORECAST_VALUES = FORECAST_EXPECTED.map((expected, i) =>
    i === 36 ? expected + 70 : i === 41 ? expected - 60 : expected + ((i * 7) % 11) - 5
)
const FORECAST_TRIGGERED = [36, 41]
const scoredOnly = (values: number[]): (number | null)[] => values.map((v, i) => (i < 30 ? null : v))

const FORECAST_RESULT: AlertSimulationResult = {
    data: FORECAST_VALUES,
    dates: FORECAST_DATES,
    scores: FORECAST_VALUES.map(() => null),
    triggered_indices: FORECAST_TRIGGERED,
    triggered_dates: FORECAST_TRIGGERED.map((i) => FORECAST_DATES[i]),
    interval: 'day',
    total_points: FORECAST_VALUES.length,
    anomaly_count: FORECAST_TRIGGERED.length,
    forecast: {
        lower_quantile: 0.01,
        upper_quantile: 0.99,
        expected: scoredOnly(FORECAST_EXPECTED),
        lower: scoredOnly(FORECAST_EXPECTED.map((v) => v - 20)),
        upper: scoredOnly(FORECAST_EXPECTED.map((v) => v + 20)),
        fired_side: FORECAST_VALUES.map((_, i) => (i === 36 ? 'above' : i === 41 ? 'below' : null)),
    },
}

function StoryFrame({ children }: { children: JSX.Element }): JSX.Element {
    return <div className="max-w-2xl border rounded bg-surface-primary p-4">{children}</div>
}

const meta: Meta = {
    title: 'Products/Alerts/Simulation summary',
    parameters: { layout: 'fullscreen' },
    decorators: [
        (Story): JSX.Element => (
            <div className="min-h-screen bg-bg-primary p-4">
                <Story />
            </div>
        ),
    ],
}

export default meta

type Story = StoryObj<typeof meta>

export const SingleScore: Story = {
    render: () => (
        <StoryFrame>
            <SimulationSummary result={SINGLE_RESULT} detectorConfig={DETECTOR_CONFIG} />
        </StoryFrame>
    ),
}

export const SubDetectorScores: Story = {
    render: () => (
        <StoryFrame>
            <SimulationSummary result={SUB_SCORES_RESULT} detectorConfig={DETECTOR_CONFIG} />
        </StoryFrame>
    ),
}

export const AIWithUnscoredPoints: Story = {
    render: () => (
        <StoryFrame>
            <SimulationSummary
                result={{ ...SINGLE_RESULT, scores: SCORES.map((score, i) => (TRIGGERED.includes(i) ? score : null)) }}
                detectorConfig={{ type: 'llm' }}
            />
        </StoryFrame>
    ),
}

export const Forecast: Story = {
    parameters: { testOptions: { snapshotBrowsers: [] } },
    render: () => (
        <StoryFrame>
            <SimulationSummary
                result={FORECAST_RESULT}
                detectorConfig={{ type: 'forecast', above: { quantile: 0.99 }, below: { quantile: 0.01 } }}
            />
        </StoryFrame>
    ),
}
