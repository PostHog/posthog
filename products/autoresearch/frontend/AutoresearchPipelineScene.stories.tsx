import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

import type {
    AutoresearchModelApi,
    AutoresearchPipelineApi,
    AutoresearchRunApi,
    AutoresearchSuggestionApi,
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
    iterations_per_run: 5,
    research_interval_days: 7,
    agent_model: null,
    agent_reasoning_effort: null,
    effective_agent_model: 'claude-opus-5-5',
    effective_agent_reasoning_effort: 'medium',
    training_phase: 'maintain',
    next_research_at: '2026-11-12T00:00:00Z',
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

const challenger = {
    ...champion,
    id: '0190c3f2-0000-7000-8000-0000000000c2',
    role: 'challenger',
    holdout_score: 0.84,
    realized_score: 0.83,
    source_training_run: 'training-4',
    agent_description: 'Gradient boosting with share counts measured up to midnight.',
    promoted_at: null,
    created_at: '2026-02-25T11:00:00Z',
} as unknown as AutoresearchModelApi

function iteration(
    iteration_number: number,
    status: 'kept' | 'discarded' | 'crashed',
    holdout_score: number | null,
    agent_description: string,
    summary: string | null = null
): Record<string, unknown> {
    return {
        iteration_number,
        status,
        holdout_score,
        train_score: null,
        agent_description,
        summary,
        model_spec: {
            model_class: 'sklearn.ensemble.HistGradientBoostingClassifier',
            model_params: { max_depth: 4, learning_rate: 0.05, random_state: 7 },
        },
    }
}

const PERFORMANCE_DATES = ['2026-02-10', '2026-02-11', '2026-02-12', '2026-02-13', '2026-02-14']

/** Top 10% counts out of 47,000 people scored, 1,410 of whom did it. */
function topTenCounts(tp: number): Record<string, number> {
    return {
        tp,
        fp: 4700 - tp,
        fn: 1410 - tp,
        tn: 47000 - 4700 - (1410 - tp),
        n_flagged: 4700,
        precision: tp / 4700,
        recall: tp / 1410,
    }
}

function performanceRow(prediction_date: string, index: number): { prediction_date: string } & Record<string, unknown> {
    return {
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
            top_10: topTenCounts([440, 480, 470, 510, 455][index]),
            top_20: { tp: 735, fp: 8665, fn: 675, tn: 36925, n_flagged: 9400, precision: 0.0782, recall: 0.5213 },
            likely: { tp: 700, fp: 3700, fn: 710, tn: 41890, n_flagged: 4400, precision: 0.1591, recall: 0.4965 },
        },
        likely_threshold: 0.09,
        calibration_bins: [
            { n: 37600, mean_p_y: 0.01, positive_rate: 0.008 },
            { n: 4700, mean_p_y: 0.08, positive_rate: 0.07 },
            { n: 2350, mean_p_y: 0.3, positive_rate: 0.27 },
            { n: 2350, mean_p_y: 0.68, positive_rate: 0.6 },
        ],
        warning: null,
        validated_at: '2026-02-21T03:00:00Z',
    }
}

// The challenger started scoring next to the champion on Feb 12, so its line covers the last three dates.
const challengerPerformance = PERFORMANCE_DATES.slice(2).map((prediction_date, index) => ({
    ...performanceRow(prediction_date, index + 2),
    validation_run_id: `validate-challenger-${index}`,
    model_id: challenger.id,
    emitted_role: 'challenger',
    current_role: 'challenger',
    mean_p_y: 0.031,
    realized_auc: [0.82, 0.84, 0.83][index],
    realized_auc_ci_low: [0.8, 0.82, 0.81][index],
    realized_auc_ci_high: [0.84, 0.86, 0.85][index],
    lift_at_10: [3.6, 3.9, 3.8][index],
    confusion: {
        top_10: { tp: 520, fp: 4180, fn: 890, tn: 41410, n_flagged: 4700, precision: 0.1106, recall: 0.3688 },
        top_20: { tp: 760, fp: 8640, fn: 650, tn: 36950, n_flagged: 9400, precision: 0.0809, recall: 0.539 },
        likely: { tp: 720, fp: 3600, fn: 690, tn: 41990, n_flagged: 4320, precision: 0.1667, recall: 0.5106 },
    },
}))

const onlinePerformance = {
    rows: [...PERFORMANCE_DATES.map(performanceRow), ...challengerPerformance].sort((a, b) =>
        b.prediction_date.localeCompare(a.prediction_date)
    ),
    segment_thresholds: {
        likely_threshold: 0.09,
        possible_threshold: 0.03,
        likely_lift: 3,
        base_rate: 0.03,
        base_rate_dates: 5,
        base_rate_source: 'realized',
        champion_mean_p_y: 0.033,
        champion_base_rate: 0.03,
        scores_miscalibrated: false,
    },
}

const newestRun = {
    id: 'training-4',
    pipeline: PIPELINE_ID,
    task_url: null,
    status: 'completed',
    iteration_count: 3,
    best_holdout_score: 0.84,
    reader_summary:
        'Found why scores on real outcomes lagged. Training counted shares up to a random time of day, but scoring counts them up to midnight. Its model is now scored next to the live one.',
    next_steps: [
        'Check the midnight cutoff on two more weeks of outcomes.',
        'Try shares per active day.',
        'Drop features that never rank in the top ten.',
    ],
    summary: {
        distillation: 'MATCHED CUTOFFS. Midnight cutoffs close most of the gap between holdout and realized AUC.',
        recommended_next: 'Validate on more matured dates before any new features.',
        kept_ladder: [],
        dead_ends: [
            { iteration_number: 1, holdout_score: 0.82, model_class: 'x', agent_description: 'Hour of day weights.' },
        ],
    },
    iterations: [
        iteration(
            0,
            'kept',
            0.82,
            'SHIPPED BUNDLE. Re-scored the live recipe the way the scoring job runs it, to get a fair baseline.',
            'Re-scored the live recipe the way scoring runs it'
        ),
        iteration(1, 'discarded', 0.82, 'Weight training rows by hour of day. No gain over the baseline.'),
        iteration(
            2,
            'kept',
            0.84,
            'Moved every training cutoff to midnight to match how scoring counts shares. This closes part of the gap.',
            'Moved training cutoffs to midnight'
        ),
    ],
    error: '',
    started_at: '2026-02-25T09:00:00Z',
    completed_at: '2026-02-25T09:39:00Z',
    created_at: '2026-02-25T09:00:00Z',
}

const suggestions = [
    {
        id: 'suggestion-1',
        pipeline: PIPELINE_ID,
        prompt: 'Try the number of people each file was shared with.',
        priority: 'consider',
        status: 'queued',
        agent_response: '',
        created_at: '2026-02-28T09:00:00Z',
    },
] as unknown as AutoresearchSuggestionApi[]

const trainingRuns = [
    {
        id: 'training-3',
        pipeline: PIPELINE_ID,
        kickoff_reason: 'scheduled',
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
        kickoff_reason: 'explore',
        agent_model: 'claude-opus-5-5',
        agent_model_label: 'Claude Opus 5.5',
        agent_reasoning_effort: 'medium',
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
        kickoff_reason: 'manual',
        agent_model: 'claude-opus-5-5',
        agent_model_label: 'Claude Opus 5.5',
        agent_reasoning_effort: 'medium',
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
                [`/api/projects/:team_id/autoresearch/${PIPELINE_ID}/models/`]: toPaginatedResponse([
                    champion,
                    challenger,
                ]),
                [`/api/projects/:team_id/autoresearch/${PIPELINE_ID}/runs/`]: toPaginatedResponse(runs),
                [`/api/projects/:team_id/autoresearch/${PIPELINE_ID}/training_runs/`]: toPaginatedResponse([
                    newestRun,
                    ...trainingRuns,
                ]),
                [`/api/projects/:team_id/autoresearch/${PIPELINE_ID}/suggestions/`]: toPaginatedResponse(suggestions),
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

// Runs from before the plain-language notes existed: the brief falls back to a line built from the scores.
export const AgentResearchWithoutReaderNotes: Story = {
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/autoresearch/${PIPELINE_ID}/models/`]: toPaginatedResponse([champion]),
                [`/api/projects/:team_id/autoresearch/${PIPELINE_ID}/training_runs/`]:
                    toPaginatedResponse(trainingRuns),
                [`/api/projects/:team_id/autoresearch/${PIPELINE_ID}/suggestions/`]: toPaginatedResponse([]),
            },
        }),
    ],
    parameters: {
        pageUrl: `${urls.autoresearchPipeline(PIPELINE_ID)}?tab=agent_research`,
        testOptions: { viewportWidths: ['wide'] },
    },
}

export const Accuracy: Story = {
    parameters: {
        pageUrl: `${urls.autoresearchPipeline(PIPELINE_ID)}?tab=accuracy`,
        testOptions: { viewportWidths: ['wide', 'narrow'] },
    },
}

export const AccuracyHitRateWithChallengers: Story = {
    parameters: {
        pageUrl: `${urls.autoresearchPipeline(PIPELINE_ID)}?tab=accuracy`,
        testOptions: {
            viewportWidths: ['wide'],
            waitForSelector: '[data-attr="autoresearch-model-accuracy-trend-cutoff-top_10"]',
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('Accuracy over time', {}, { timeout: 15000 })
        await userEvent.click(
            canvasElement.querySelector(
                '[data-attr="autoresearch-model-accuracy-trend-metric-hit_rate"]'
            ) as HTMLElement
        )
        await userEvent.click(await canvas.findByText('Compare challengers'))
    },
}

export const AccuracyBeforePrecisionRecall: Story = {
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/autoresearch/${PIPELINE_ID}/online_performance/`]: {
                    ...onlinePerformance,
                    rows: onlinePerformance.rows.map((row) => ({
                        ...row,
                        average_precision: null,
                        confusion: null,
                        likely_threshold: null,
                    })),
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
