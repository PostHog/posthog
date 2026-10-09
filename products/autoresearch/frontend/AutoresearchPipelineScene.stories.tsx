import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

import type {
    AutoresearchModelApi,
    AutoresearchPipelineApi,
    AutoresearchRunApi,
    AutoresearchTrainingRunApi,
} from './generated/api.schemas'

const PIPELINE_ID = '0190c3f2-0000-7000-8000-000000000001'

const pipeline = {
    id: PIPELINE_ID,
    name: 'File sharers',
    description: '',
    target_event: 'file_shared',
    target_definition: { type: 'event' },
    horizon_days: 7,
    training_lookback_days: 90,
    training_population: {},
    inference_population: {},
    cadence_days: 1,
    iteration_budget: 20,
    iteration_budget_remaining: 6,
    success_auc: null,
    plateau_iterations: 5,
    output_person_property: 'p_file_shared_7d',
    status: 'running',
    created_by: {
        id: 1,
        uuid: '0190c3f2-0000-7000-8000-0000000000aa',
        distinct_id: 'storybook-user',
        first_name: 'Hedge',
        email: 'hedge@example.com',
    },
    created_at: '2026-01-01T09:00:00Z',
    updated_at: '2026-03-01T03:00:00Z',
    last_scored_at: '2026-03-01T03:00:00Z',
    champion_holdout_auc: 0.83,
    champion_realized_auc: 0.81,
    champion_lift_at_10: 3.4,
    champion_is_preliminary: false,
    champion_realized_auc_trend: [],
    people_scored: 48210,
    training_run_count: 2,
    experiment_count: 14,
    live_training_run: null,
} as unknown as AutoresearchPipelineApi

const champion = {
    id: '0190c3f2-0000-7000-8000-0000000000c1',
    pipeline: PIPELINE_ID,
    role: 'champion',
    recipe_hash: 'abc123',
    model_recipe: {},
    model_explanation: {
        method: 'gain on the holdout split',
        top_features: [
            { name: 'files_uploaded_7d', importance: 0.42, direction: 'positive' },
            { name: 'days_since_last_share', importance: 0.31, direction: 'negative' },
        ],
    },
    holdout_score: 0.83,
    realized_score: 0.81,
    calibration_error: 0.04,
    metrics: {},
    source_training_run: null,
    agent_description: 'Gradient boosting on recent sharing and upload activity.',
    is_preliminary: false,
    promoted_at: '2026-01-10T00:00:00Z',
} as unknown as AutoresearchModelApi

const runs = [
    { id: 'score-1', run_type: 'inference', status: 'completed', created_at: '2026-02-10T03:00:00Z', metrics: {} },
    { id: 'score-2', run_type: 'inference', status: 'completed', created_at: '2026-02-11T03:00:00Z', metrics: {} },
    { id: 'score-3', run_type: 'inference', status: 'completed', created_at: '2026-03-01T03:00:00Z', metrics: {} },
    {
        id: 'validate-1',
        run_type: 'validation',
        status: 'completed',
        created_at: '2026-02-18T03:00:00Z',
        metrics: {
            prediction_date: '2026-02-10',
            per_model: {
                [champion.id]: {
                    model_role: 'champion',
                    emitted_role: 'champion',
                    n_scored: 47000,
                    realized_auc: 0.81,
                    brier_score: 0.06,
                    calibration_error: 0.04,
                    lift_at_10: 3.4,
                    lift_at_20: 2.6,
                },
            },
        },
    },
] as unknown as AutoresearchRunApi[]

const trainingRuns = [
    {
        id: 'training-1',
        pipeline: PIPELINE_ID,
        task_url: null,
        status: 'completed',
        iteration_count: 14,
        best_holdout_score: 0.83,
        summary: null,
        iterations: [],
        error: '',
        started_at: '2026-01-09T09:00:00Z',
        completed_at: '2026-01-10T00:00:00Z',
        created_at: '2026-01-09T09:00:00Z',
    },
] as unknown as AutoresearchTrainingRunApi[]

const meta: Meta = {
    component: App,
    title: 'Products/Autoresearch/Model detail scene',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-03-01T12:00:00Z',
        featureFlags: [FEATURE_FLAGS.AUTORESEARCH],
        pageUrl: urls.autoresearchPipeline(PIPELINE_ID),
    },
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/autoresearch/${PIPELINE_ID}/`]: pipeline,
                [`/api/projects/:team_id/autoresearch/${PIPELINE_ID}/models/`]: toPaginatedResponse([champion]),
                [`/api/projects/:team_id/autoresearch/${PIPELINE_ID}/runs/`]: toPaginatedResponse(runs),
                [`/api/projects/:team_id/autoresearch/${PIPELINE_ID}/training_runs/`]:
                    toPaginatedResponse(trainingRuns),
                [`/api/projects/:team_id/autoresearch/${PIPELINE_ID}/suggestions/`]: toPaginatedResponse([]),
            },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof meta>

export const Wide: Story = {
    parameters: { testOptions: { viewportWidths: ['wide'] } },
}

export const Narrow: Story = {
    parameters: { testOptions: { viewportWidths: ['narrow'] } },
}
