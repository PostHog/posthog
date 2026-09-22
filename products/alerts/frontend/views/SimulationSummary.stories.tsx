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
