import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

import type {
    EvaluationApi,
    EvaluationResultApi,
    EvaluationRunsApi,
    EvaluationsOverviewApi,
    PassRateOverviewEntryApi,
    ScoreHistogramApi,
} from '../../generated/api.schemas'

const DAYS = Array.from({ length: 14 }, (_, index) => `2026-10-${String(7 + index).padStart(2, '0')}T00:00:00+00:00`)

/** A smooth, repeatable daily series around `base`, so stories render the same every time. */
function wave(base: number, swing: number, phase: number): number[] {
    return DAYS.map((_, index) => Math.round((base + swing * Math.sin(index / 2 + phase)) * 10) / 10)
}

function volume(perDay: number): number[] {
    return DAYS.map((_, index) => perDay + ((index * 7) % 5) * Math.round(perDay / 10))
}

function sum(values: number[]): number {
    return values.reduce((total, value) => total + value, 0)
}

function uuid(index: number): string {
    return `0b1e0000-0000-4000-8000-${index.toString(16).padStart(12, '0')}`
}

type ResultOverrides = Partial<EvaluationResultApi> & Pick<EvaluationResultApi, 'id' | 'name' | 'summary'>

function result(overrides: ResultOverrides): EvaluationResultApi {
    return {
        directoryName: null,
        evaluationType: 'llm_judge',
        outputType: 'boolean',
        enabled: true,
        statusReason: null,
        createdBy: 'Ada Example',
        gradedCount: 0,
        previousGradedCount: null,
        notApplicableCount: 0,
        skippedCount: 0,
        lastRunAt: '2026-10-20T09:00:00Z',
        trend: { values: DAYS.map(() => null), volume: DAYS.map(() => 0) },
        change: null,
        lowEvidence: false,
        attentionReasons: [],
        bucketStatus: DAYS.map(() => 'none'),
        trackedCategory: null,
        ...overrides,
    }
}

function passRateResult(
    id: string,
    name: string,
    rate: number,
    previous: number | null,
    perDay: number,
    swing = 2
): EvaluationResultApi {
    const values = wave(rate, swing, id.length)
    const daily = volume(perDay)
    const graded = sum(daily)
    const passed = Math.round((graded * rate) / 100)
    const change = previous === null ? null : Math.round((rate - previous) * 10) / 10
    return result({
        id,
        name,
        gradedCount: graded,
        previousGradedCount: previous === null ? null : Math.round(graded * 0.94),
        summary: {
            kind: 'pass_rate',
            passed,
            failed: graded - passed,
            previous:
                previous === null
                    ? null
                    : {
                          passed: Math.round((graded * previous) / 100),
                          failed: graded - Math.round((graded * previous) / 100),
                      },
            score: null,
        },
        trend: { values, volume: daily },
        change: change === null ? null : { value: change, unit: 'pp', subject: null },
        lowEvidence: graded < 30,
        attentionReasons: change !== null && change <= -2 ? ['worse'] : [],
        bucketStatus: values.map((value) => (previous !== null && value <= previous - 3 ? 'dip' : 'normal')),
    })
}

const HELPFULNESS = passRateResult(uuid(1), 'Helpfulness', 91.4, 92.0, 140)
const GROUNDEDNESS = passRateResult(uuid(2), 'Answer is grounded in context', 78.2, 86.5, 90, 4)
const TONE = passRateResult(uuid(3), 'Polite tone', 97.1, 96.4, 60, 1)
const NEW_CHECK = passRateResult(uuid(4), 'Refuses off-topic requests', 70, null, 1)
// Names that only differ at the end, which a plain truncation hides.
const SIMILAR_NAMES = [
    passRateResult(uuid(21), 'Answer is grounded in the retrieved tool results', 61.5, 63.0, 80, 3),
    passRateResult(uuid(22), 'Answer is grounded in the retrieved tool results (fast model)', 82.4, 81.0, 70, 2),
    passRateResult(uuid(23), 'Answer is grounded in the retrieved tool results (decision model)', 90.2, 89.5, 60, 2),
]

const SENTIMENT_VALUES = wave(14, 3, 1)
const SENTIMENT = result({
    id: uuid(5),
    name: 'User sentiment',
    evaluationType: 'sentiment',
    outputType: 'sentiment',
    gradedCount: 3640,
    previousGradedCount: 3410,
    summary: { kind: 'sentiment', positive: 1820, neutral: 1310, negative: 510, previousNegativeShare: 12.1 },
    trend: { values: SENTIMENT_VALUES, volume: volume(250) },
    change: { value: 1.9, unit: 'pp', subject: 'negative' },
    bucketStatus: SENTIMENT_VALUES.map((value) => (value >= 15.1 ? 'dip' : 'normal')),
})

const INTENT = result({
    id: uuid(6),
    name: 'Request intent',
    outputType: 'categorical',
    gradedCount: 1960,
    previousGradedCount: 1880,
    summary: {
        kind: 'categories',
        multiple: false,
        categories: [
            { key: 'billing', label: 'Billing', count: 820, previousShare: 38.2 },
            { key: 'bug', label: 'Bug report', count: 640, previousShare: 36.9 },
            { key: 'other', label: 'Other', count: 500, previousShare: 24.9 },
        ],
        noCategoriesCount: 0,
    },
    trend: { values: wave(41.8, 2, 2), volume: volume(140) },
    change: { value: 3.6, unit: 'pp', subject: 'Billing' },
    bucketStatus: DAYS.map((_, index) => (index === 9 ? 'dip' : 'normal')),
    trackedCategory: 'billing',
})

const SCORE = result({
    id: uuid(7),
    name: 'Answer completeness',
    outputType: 'numeric',
    gradedCount: 1120,
    previousGradedCount: 1050,
    summary: { kind: 'score', score: { mean: 3.8, scale: { min: 1, max: 5 } }, previousMean: 3.9 },
    trend: { values: wave(3.8, 0.15, 3), volume: volume(80) },
    change: { value: -0.1, unit: 'points', subject: null },
    bucketStatus: DAYS.map(() => 'normal'),
})

const ERRORED = result({
    id: uuid(8),
    name: 'Cites a source',
    enabled: false,
    statusReason: 'provider_key_quota_exceeded',
    lastRunAt: '2026-10-12T14:00:00Z',
    summary: { kind: 'pass_rate', passed: 0, failed: 0, previous: null, score: null },
    attentionReasons: ['errored'],
})

const SILENT = result({
    id: uuid(9),
    name: 'Mentions pricing correctly',
    lastRunAt: '2026-10-03T08:00:00Z',
    summary: { kind: 'pass_rate', passed: 0, failed: 0, previous: null, score: null },
    attentionReasons: ['silent'],
})

const PAUSED = result({
    id: uuid(10),
    name: 'Hallucination check',
    enabled: false,
    lastRunAt: '2026-09-28T08:00:00Z',
    summary: { kind: 'pass_rate', passed: 0, failed: 0, previous: null, score: null },
})

function median(values: number[]): number | null {
    if (values.length === 0) {
        return null
    }
    const sorted = [...values].sort((a, b) => a - b)
    const middle = Math.floor(sorted.length / 2)
    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

function rateOf(row: EvaluationResultApi): number {
    return row.summary.kind === 'pass_rate' ? (row.summary.passed / row.gradedCount) * 100 : NaN
}

function previousRateOf(row: EvaluationResultApi): number | null {
    const previous = row.summary.kind === 'pass_rate' ? row.summary.previous : null
    return previous ? (previous.passed / (previous.passed + previous.failed)) * 100 : null
}

/** Totals built from the rows, the way the backend builds them, so the tabs agree with the chart. */
function overview(evaluations: EvaluationResultApi[]): EvaluationsOverviewApi {
    const active = evaluations.filter((row) => row.enabled)
    const passRates = active.filter((row) => row.summary.kind === 'pass_rate' && row.gradedCount > 0)
    const measured = passRates.filter((row) => !row.lowEvidence)
    const compared = measured.filter((row) => previousRateOf(row) !== null)
    const both = active.filter((row) => row.gradedCount > 0 && row.previousGradedCount !== null)
    const entries: PassRateOverviewEntryApi[] = passRates
        .map((row) => ({ evaluationId: row.id, rate: rateOf(row), lowEvidence: row.lowEvidence }))
        .sort((a, b) => a.rate - b.rate)
    const currentMedian = median(compared.map(rateOf))
    const previousMedian = median(compared.map((row) => previousRateOf(row) ?? 0))
    const sentiment = active.find((row) => row.summary.kind === 'sentiment' && row.gradedCount > 0)
    return {
        start: DAYS[0],
        end: '2026-10-21T00:00:00+00:00',
        previousStart: '2026-09-23T00:00:00+00:00',
        previousEnd: DAYS[0],
        interval: 'day',
        buckets: DAYS,
        evaluations,
        totals: {
            graded: sum(active.map((row) => row.gradedCount)),
            gradedComparison:
                both.length > 0
                    ? {
                          current: sum(both.map((row) => row.gradedCount)),
                          previous: sum(both.map((row) => row.previousGradedCount ?? 0)),
                      }
                    : null,
            gradedTrend: DAYS.map((_, index) => sum(active.map((row) => row.trend.volume[index]))),
            sentiment:
                sentiment && sentiment.summary.kind === 'sentiment'
                    ? {
                          evaluationId: sentiment.id,
                          negativeShare: (sentiment.summary.negative / sentiment.gradedCount) * 100,
                          previousShare: sentiment.summary.previousNegativeShare,
                      }
                    : null,
        },
        passRateOverview: {
            entries,
            median: median(measured.map(rateOf)),
            medianComparison:
                currentMedian !== null && previousMedian !== null
                    ? { current: currentMedian, previous: previousMedian }
                    : null,
            medianTrend: measured.length
                ? DAYS.map((_, index) =>
                      median(measured.map((row) => row.trend.values[index]).filter((value) => value !== null))
                  )
                : [],
        },
    }
}

const SUPPORT_DIRECTORY = {
    id: '0b1ed100-0000-4000-8000-000000000001',
    name: 'Support bot',
    created_at: '2026-09-01T10:00:00Z',
    updated_at: null,
    created_by: null,
    evaluation_count: 2,
}

const SEARCH_DIRECTORY = {
    ...SUPPORT_DIRECTORY,
    id: '0b1ed100-0000-4000-8000-000000000002',
    name: 'Search assistant',
    evaluation_count: 3,
}

const DIRECTORIES = [SUPPORT_DIRECTORY, SEARCH_DIRECTORY]

/** The list entry the scene's table and scope picker read, for one overview row. */
function listEntry(row: EvaluationResultApi): EvaluationApi {
    return {
        id: row.id,
        name: row.name,
        description: '',
        directory_id: DIRECTORIES.find((directory) => directory.name === row.directoryName)?.id ?? null,
        enabled: row.enabled,
        status: row.statusReason ? 'error' : row.enabled ? 'active' : 'paused',
        status_reason: row.statusReason as EvaluationApi['status_reason'],
        status_reason_detail: null,
        evaluation_type: row.evaluationType as EvaluationApi['evaluation_type'],
        evaluation_config:
            row.evaluationType === 'sentiment' ? {} : { prompt: `Check this response for: ${row.name.toLowerCase()}` },
        output_type: row.outputType as EvaluationApi['output_type'],
        output_config:
            row.outputType === 'categorical'
                ? { options: [{ key: 'billing', label: 'Billing' }] }
                : row.outputType === 'numeric'
                  ? { min: 1, max: 5 }
                  : {},
        conditions: [],
        target: row.evaluationType === 'sentiment' ? 'trace' : 'generation',
        model_configuration: null,
        created_at: '2026-09-01T10:00:00Z',
        updated_at: '2026-10-01T10:00:00Z',
        created_by: null,
        deleted: false,
        user_access_level: 'editor',
    }
}

const FAILURES: Record<string, string[]> = {
    [GROUNDEDNESS.id]: [
        'The answer promises a full-year refund. The retrieved policy only allows refunds within 30 days.',
        'No retrieved document mentions an export schedule, so the stated time is not supported.',
        'The reply names a plan tier that does not appear in the provided pricing context.',
    ],
}

/** Invented failing runs for one evaluation, newest first, matching the shape the runs endpoint returns. */
function failingRuns(id: string): EvaluationRunsApi {
    return {
        results: (FAILURES[id] ?? []).map((reasoning, index) => ({
            timestamp: `2026-10-19T0${9 - index}:12:00Z`,
            outcome: 'failed',
            reasoning,
            targetEventId: `0b1ee000-0000-4000-8000-00000000000${index}`,
            traceId: `trace-example-${index}`,
        })),
    }
}

const SCORE_HISTOGRAM: ScoreHistogramApi = {
    scale: { min: 1, max: 5 },
    buckets: [
        { label: '1', count: 40 },
        { label: '2', count: 96 },
        { label: '3', count: 210 },
        { label: '4', count: 452 },
        { label: '5', count: 322 },
    ],
}

function scene(rows: EvaluationResultApi[], { rateLimited = false } = {}): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/api/projects/:team_id/evaluations/': toPaginatedResponse(rows.map(listEntry)),
            '/api/projects/:team_id/evaluations/overview/': ({ request }) => {
                if (rateLimited) {
                    return [429, { type: 'throttled_error', detail: 'Too many queries are running.' }]
                }
                const ids = new URL(request.url).searchParams.get('evaluation_ids')?.split(',')
                return [200, overview(ids ? rows.filter((row) => ids.includes(row.id)) : rows)]
            },
            '/api/projects/:team_id/evaluations/:id/runs/': ({ params }) => [200, failingRuns(String(params.id))],
            '/api/projects/:team_id/evaluations/:id/score_distribution/': SCORE_HISTOGRAM,
            '/api/projects/:team_id/evaluation_directories/': DIRECTORIES.filter((directory) =>
                rows.some((row) => row.directoryName === directory.name)
            ),
            '/api/environments/:team_id/llm_analytics/provider_keys/': toPaginatedResponse([]),
            '/api/projects/:team_id/llm_analytics/provider_keys/': toPaginatedResponse([]),
            '/api/environments/:team_id/llm_analytics/evaluation_config/': { active_provider_key: null },
        },
        post: {
            '/api/environments/:team_id/query/': { results: [] },
            '/api/projects/:team_id/query/': { results: [] },
        },
    })
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/AI observability/Evaluations overview',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-20',
        pageUrl: urls.aiObservabilityEvaluations(),
        testOptions: { waitForLoadersToDisappear: true },
    },
}
export default meta
type Story = StoryObj<{}>

const MANY = [HELPFULNESS, GROUNDEDNESS, TONE, NEW_CHECK, SENTIMENT, INTENT, SCORE, ERRORED, SILENT, PAUSED]

export const ManyEvaluations: Story = { decorators: [scene(MANY)] }

function openDrawer(name: string): Story['play'] {
    return async ({ canvasElement }) => {
        const selector = '[data-attr="evaluation-overview-table-name"]'
        await userEvent.click(await within(canvasElement).findByText(name, { selector }))
    }
}

const IN_DIRECTORIES = [
    { ...HELPFULNESS, directoryName: SUPPORT_DIRECTORY.name },
    { ...GROUNDEDNESS, directoryName: SUPPORT_DIRECTORY.name },
    { ...TONE, directoryName: SEARCH_DIRECTORY.name },
    { ...INTENT, directoryName: SEARCH_DIRECTORY.name },
    { ...ERRORED, directoryName: SEARCH_DIRECTORY.name },
    NEW_CHECK,
    SENTIMENT,
    SCORE,
    SILENT,
    PAUSED,
]

export const ManyEvaluationsWithDirectories: Story = { decorators: [scene(IN_DIRECTORIES)] }

export const DirectoryOpen: Story = {
    parameters: { pageUrl: `${urls.aiObservabilityEvaluations()}?directory=${SEARCH_DIRECTORY.id}` },
    decorators: [scene(IN_DIRECTORIES)],
}

export const DrawerPassRate: Story = { decorators: [scene(MANY)], play: openDrawer(GROUNDEDNESS.name) }

export const DrawerScore: Story = { decorators: [scene(MANY)], play: openDrawer(SCORE.name) }

export const DrawerCategories: Story = { decorators: [scene(MANY)], play: openDrawer(INTENT.name) }

export const DrawerSentiment: Story = { decorators: [scene(MANY)], play: openDrawer(SENTIMENT.name) }

export const DrawerEmptyEnabled: Story = { decorators: [scene(MANY)], play: openDrawer(SILENT.name) }

export const DrawerEmptyDisabled: Story = { decorators: [scene(MANY)], play: openDrawer(PAUSED.name) }

export const DrawerEmptyErrored: Story = { decorators: [scene(MANY)], play: openDrawer(ERRORED.name) }

export const RateLimited: Story = { decorators: [scene(MANY, { rateLimited: true })] }

// Most teams run one or two evaluations, so the page has to hold up with very little in it.
export const TwoEvaluations: Story = { decorators: [scene([GROUNDEDNESS, TONE])] }

export const NothingGraded: Story = { decorators: [scene([SILENT, PAUSED])] }

export const SimilarNames: Story = { decorators: [scene(SIMILAR_NAMES)] }
