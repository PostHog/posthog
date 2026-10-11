import { Meta, StoryObj } from '@storybook/react'

import { AutoresearchModelCard } from './AutoresearchModelCard'
import type { AutoresearchPipelineApi } from './generated/api.schemas'

const meta: Meta<typeof AutoresearchModelCard> = {
    title: 'Products/Autoresearch/Model card',
    component: AutoresearchModelCard,
    parameters: { mockDate: '2026-03-01T12:00:00Z' },
    decorators: [
        (Story) => (
            <div className="w-80">
                <Story />
            </div>
        ),
    ],
}
export default meta
type Story = StoryObj<typeof AutoresearchModelCard>

const BASE = {
    id: '0190c3f2-0000-7000-8000-000000000001',
    name: 'File sharers',
    target_event: 'file_shared',
    horizon_days: 7,
    cadence_days: 1,
    iteration_budget: 8,
    success_auc: null,
    status: 'running',
    created_at: '2026-02-01T09:00:00Z',
    last_scored_at: '2026-03-01T03:00:00Z',
    champion_holdout_auc: 0.83,
    champion_realized_auc: null,
    champion_lift_at_10: null,
    champion_is_preliminary: null,
    champion_realized_auc_trend: [],
    champion_training_trend: [0.68, 0.71, 0.71, 0.76, 0.79, 0.79, 0.83, 0.83].map((best_holdout_score, i) => ({
        iteration_number: i,
        best_holdout_score,
    })),
    people_scored: 48210,
    likely_count: 1240,
    likely_threshold: 0.6,
    first_check_expected_at: '2026-03-04T01:00:00Z',
    coverage: null,
    training_run_count: 1,
    experiment_count: 8,
    live_training_run: null,
} as unknown as AutoresearchPipelineApi

const LIVE_RUN: AutoresearchPipelineApi['live_training_run'] = {
    id: 'training-2',
    iteration_budget: 8,
    experiment_count: 3,
    best_holdout_score: 0.81,
    latest_agent_description: 'Add the ratio of shares in the last 7 days to the last 30 days.',
}

const CONFIRMED = {
    ...BASE,
    champion_realized_auc: 0.84,
    champion_lift_at_10: 2.3,
    champion_is_preliminary: false,
    champion_realized_auc_trend: [0.79, 0.81, 0.8, 0.82, 0.84, 0.83, 0.84].map((realized_auc, i) => ({
        prediction_date: `2026-02-${String(18 + i).padStart(2, '0')}`,
        realized_auc,
    })),
    likely_threshold: 0.09,
    first_check_expected_at: null,
    training_run_count: 2,
} as AutoresearchPipelineApi

export const Draft: Story = {
    args: {
        pipeline: {
            ...BASE,
            status: 'draft',
            champion_holdout_auc: null,
            champion_training_trend: [],
            people_scored: null,
            likely_count: null,
            likely_threshold: null,
            first_check_expected_at: null,
            last_scored_at: null,
            training_run_count: 0,
            experiment_count: 0,
        },
    },
}

export const Training: Story = {
    args: {
        pipeline: {
            ...Draft.args!.pipeline!,
            status: 'bootstrapping',
            training_run_count: 1,
            experiment_count: 3,
            live_training_run: LIVE_RUN,
        },
    },
}

export const AwaitingCheck: Story = { args: { pipeline: BASE } }

export const AwaitingCheckLongHorizon: Story = {
    args: {
        pipeline: {
            ...BASE,
            name: 'Upgraders',
            target_event: 'plan_upgraded',
            horizon_days: 30,
            likely_count: 312,
            first_check_expected_at: '2026-03-28T01:00:00Z',
        },
    },
}

export const AwaitingCheckWithoutLikelyCount: Story = {
    args: { pipeline: { ...BASE, likely_count: null, likely_threshold: null, first_check_expected_at: null } },
}

export const Confirmed: Story = { args: { pipeline: CONFIRMED } }

export const ConfirmedRetraining: Story = { args: { pipeline: { ...CONFIRMED, live_training_run: LIVE_RUN } } }
