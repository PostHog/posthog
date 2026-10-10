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
    training_run_count: 3,
    experiment_count: 11,
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
    source_training_run: 'training-2',
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

function iteration(
    iteration_number: number,
    status: 'kept' | 'discarded' | 'crashed',
    holdout_score: number | null,
    agent_description: string
): Record<string, unknown> {
    return {
        iteration_number,
        status,
        holdout_score,
        train_score: null,
        agent_description,
        model_spec: { model_class: 'sklearn.ensemble.HistGradientBoostingClassifier', model_params: { max_depth: 4 } },
    }
}

const onlinePerformance = {
    rows: ['2026-02-10', '2026-02-11', '2026-02-12', '2026-02-13', '2026-02-14']
        .map((prediction_date, index) => ({
            validation_run_id: `validate-${index}`,
            prediction_date,
            horizon_days: 7,
            weekday: 1,
            model_id: champion.id,
            emitted_role: 'champion',
            current_role: 'champion',
            n_scored: 47000,
            n_positive: 1410,
            base_rate: 0.03,
            mean_p_y: 0.033,
            realized_auc: [0.78, 0.8, 0.79, 0.82, 0.81][index],
            realized_auc_ci_low: [0.76, 0.78, 0.77, 0.8, 0.79][index],
            realized_auc_ci_high: [0.8, 0.82, 0.81, 0.84, 0.83][index],
            brier_score: 0.06,
            calibration_error: 0.04,
            lift_at_10: 3.4,
            lift_at_20: 2.6,
            average_precision: 0.21,
            confusion: {
                top_10: { tp: 480, fp: 4220, fn: 930, tn: 41370, n_flagged: 4700, precision: 0.1021, recall: 0.3404 },
                top_20: { tp: 735, fp: 8665, fn: 675, tn: 36925, n_flagged: 9400, precision: 0.0782, recall: 0.5213 },
                likely: { tp: 0, fp: 0, fn: 1410, tn: 45590, n_flagged: 0, precision: null, recall: 0 },
            },
            calibration_bins: [
                { n: 37600, mean_p_y: 0.01, positive_rate: 0.008 },
                { n: 4700, mean_p_y: 0.08, positive_rate: 0.07 },
                { n: 2350, mean_p_y: 0.3, positive_rate: 0.27 },
                { n: 2350, mean_p_y: 0.68, positive_rate: 0.6 },
            ],
            warning: null,
            validated_at: '2026-02-21T03:00:00Z',
        }))
        .reverse(),
}

const trainingRuns = [
    {
        id: 'training-3',
        pipeline: PIPELINE_ID,
        task_url: null,
        status: 'failed',
        iteration_count: 0,
        best_holdout_score: null,
        summary: null,
        iterations: [
            iteration(0, 'discarded', 0.81, 'Add the day of week of the last share.'),
            iteration(1, 'crashed', null, 'Join folder metadata. The feature query timed out.'),
        ],
        error: 'The sandbox stopped before the run finished.',
        started_at: '2026-02-20T09:00:00Z',
        completed_at: '2026-02-20T10:00:00Z',
        created_at: '2026-02-20T09:00:00Z',
    },
    {
        id: 'training-2',
        pipeline: PIPELINE_ID,
        task_url: null,
        status: 'completed',
        iteration_count: 5,
        best_holdout_score: 0.83,
        summary: {
            distillation: 'Recent upload counts carry most of the signal. Log scaling them helps.',
            recommended_next: 'Try a ratio of shares in the last 7 days to the last 30 days.',
        },
        iterations: [
            iteration(0, 'kept', 0.79, 'Start from the current champion.'),
            iteration(1, 'discarded', 0.78, 'Drop the team size feature.'),
            iteration(2, 'kept', 0.81, 'Log scale the upload counts.'),
            iteration(3, 'discarded', 0.8, 'Deeper trees.'),
            iteration(4, 'kept', 0.83, 'Add uploads in the last 7 days.'),
        ],
        error: '',
        started_at: '2026-01-20T09:00:00Z',
        completed_at: '2026-01-20T11:00:00Z',
        created_at: '2026-01-20T09:00:00Z',
    },
    {
        id: 'training-1',
        pipeline: PIPELINE_ID,
        task_url: null,
        status: 'completed',
        iteration_count: 4,
        best_holdout_score: 0.79,
        summary: null,
        iterations: [
            iteration(0, 'kept', 0.68, 'Baseline: event counts in the last 30 days.'),
            iteration(1, 'kept', 0.74, 'Add days since the last share.'),
            iteration(2, 'discarded', 0.72, 'Logistic regression instead of boosting.'),
            iteration(3, 'kept', 0.79, 'Add the number of files uploaded.'),
        ],
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
                [`/api/projects/:team_id/autoresearch/${PIPELINE_ID}/online_performance/`]: onlinePerformance,
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

export const AgentResearchWide: Story = {
    parameters: {
        pageUrl: `${urls.autoresearchPipeline(PIPELINE_ID)}?tab=agent_research`,
        testOptions: { viewportWidths: ['wide'] },
    },
}

export const AgentResearchNarrow: Story = {
    parameters: {
        pageUrl: `${urls.autoresearchPipeline(PIPELINE_ID)}?tab=agent_research`,
        testOptions: { viewportWidths: ['narrow'] },
    },
}

export const Accuracy: Story = {
    parameters: {
        pageUrl: `${urls.autoresearchPipeline(PIPELINE_ID)}?tab=accuracy`,
        testOptions: { viewportWidths: ['wide', 'narrow'] },
    },
}

export const AccuracyBeforePrecisionRecall: Story = {
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/autoresearch/${PIPELINE_ID}/online_performance/`]: {
                    rows: onlinePerformance.rows.map((row) => ({ ...row, average_precision: null, confusion: null })),
                },
            },
        }),
    ],
    parameters: {
        pageUrl: `${urls.autoresearchPipeline(PIPELINE_ID)}?tab=accuracy`,
        testOptions: { viewportWidths: ['wide'] },
    },
}

function coverageRuns(days: number, perDay: (day: number) => Partial<AutoresearchRunApi>): AutoresearchRunApi[] {
    return Array.from({ length: days }, (_, day) => ({
        id: `coverage-${day}`,
        pipeline: PIPELINE_ID,
        run_type: 'inference',
        status: 'completed',
        error: '',
        created_at: `2026-02-${String(day + 16).padStart(2, '0')}T03:00:00Z`,
        ...perDay(day),
    })) as unknown as AutoresearchRunApi[]
}

function coverageStory(coverageRunList: AutoresearchRunApi[]): Story {
    return {
        decorators: [
            mswDecorator({
                get: {
                    [`/api/projects/:team_id/autoresearch/${PIPELINE_ID}/runs/`]: toPaginatedResponse(coverageRunList),
                },
            }),
        ],
        parameters: {
            pageUrl: `${urls.autoresearchPipeline(PIPELINE_ID)}?tab=predictions`,
            testOptions: { viewportWidths: ['wide', 'narrow'] },
        },
    }
}

// Everyone fits under the scoring cap, so each run rescores the whole population.
export const CoverageBelowCap: Story = coverageStory(
    coverageRuns(12, (day) => ({
        rows_scored: 48000,
        metrics: { rows_eligible: 48000 },
        coverage: {
            population: 48000,
            with_score: day === 0 ? 0 : 48000,
            never_scored: day === 0 ? 48000 : 0,
            age_days_avg: day === 0 ? null : 1,
            age_days_p50: day === 0 ? null : 1,
            age_days_p90: day === 0 ? null : 1,
            age_days_max: day === 0 ? null : 1,
            lookback_days: 30,
        },
    }))
)

// Each run scores 45,000 of 250,000 people, and the first rotation is not complete yet.
export const CoverageRollingMidCycle: Story = coverageStory(
    coverageRuns(5, (day) => ({
        rows_scored: 45000,
        metrics: { rows_eligible: 250000 },
        coverage: {
            population: 250000,
            with_score: 45000 * day,
            never_scored: 250000 - 45000 * day,
            age_days_avg: day === 0 ? null : (day - 1) / 2,
            age_days_p50: day === 0 ? null : (day - 1) / 2,
            age_days_p90: day === 0 ? null : (day - 1) * 0.9,
            age_days_max: day === 0 ? null : day - 1,
            lookback_days: 30,
        },
    }))
)

// Failed runs leave gaps, so the oldest scores are older than the daily target.
export const CoverageWithFailedRuns: Story = coverageStory(
    coverageRuns(14, (day) => {
        if ([5, 6, 10, 11, 13].includes(day)) {
            return {
                status: 'failed',
                rows_scored: null,
                metrics: {},
                coverage: null,
                error: 'The scoring query timed out.',
            }
        }
        const age = day === 7 || day === 12 ? 3 : 1
        return {
            rows_scored: 48000,
            metrics: { rows_eligible: 48000 },
            coverage: {
                population: 48000,
                with_score: day === 0 ? 0 : 48000,
                never_scored: day === 0 ? 48000 : 0,
                age_days_avg: day === 0 ? null : age,
                age_days_p50: day === 0 ? null : age,
                age_days_p90: day === 0 ? null : age,
                age_days_max: day === 0 ? null : age,
                lookback_days: 30,
            },
        }
    })
)
