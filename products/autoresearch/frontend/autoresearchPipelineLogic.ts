import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { hogql } from '~/queries/utils'
import { Breadcrumb } from '~/types'

import type { FeatureFlagsSet } from '../../../frontend/src/lib/logic/featureFlagLogic'
import {
    autoresearchModelsList,
    autoresearchPauseCreate,
    autoresearchResumeCreate,
    autoresearchRetrieve,
    autoresearchRunsList,
    autoresearchRunsRetrieve,
    autoresearchScoreCreate,
    autoresearchSuggestionsCreate,
    autoresearchSuggestionsList,
    autoresearchTrainingRunsArtifactsGetCreate,
    autoresearchTrainingRunsArtifactsRetrieve,
    autoresearchTrainingRunsList,
    autoresearchTrainCreate,
} from './generated/api'
import {
    AutoresearchModelRoleEnumApi,
    type AutoresearchModelApi,
    type AutoresearchPipelineApi,
    type AutoresearchRunApi,
    type AutoresearchSuggestionApi,
    type AutoresearchTrainingRunApi,
    CreateSuggestionPriorityEnumApi,
    type ModelExplanationFieldApi,
} from './generated/api.schemas'
import type { PredictionsPeopleView } from './predictionsPeopleQuery'

export interface AutoresearchPipelineLogicProps {
    id: string
}

export type AutoresearchPipelineTab = 'overview' | 'training' | 'predictions' | 'online_performance' | 'suggestions'

const AUTORESEARCH_PIPELINE_TABS: AutoresearchPipelineTab[] = [
    'overview',
    'training',
    'predictions',
    'online_performance',
    'suggestions',
]

function isPipelineTab(value: string | undefined): value is AutoresearchPipelineTab {
    return value !== undefined && (AUTORESEARCH_PIPELINE_TABS as string[]).includes(value)
}

/** How often the Score now button checks a running scoring run. */
export const SCORE_RUN_POLL_INTERVAL_MS = 5000

/** Matches the backend cutoff: a run still running after the workflow timeout lost its worker. */
export const SCORE_RUN_STALE_AFTER_MS = 5 * 60 * 60 * 1000

function isScoreRunInProgress(run: AutoresearchRunApi): boolean {
    return run.status === 'running' || run.status === 'pending'
}

/** The inference run that is scoring now, if any. Scoring runs in the background, so a reload resumes from it. */
function findRunningScoreRun(runs: AutoresearchRunApi[]): AutoresearchRunApi | null {
    const cutoff = Date.now() - SCORE_RUN_STALE_AFTER_MS
    return (
        runs.find(
            (r) =>
                r.run_type === 'inference' &&
                isScoreRunInProgress(r) &&
                new Date(r.started_at ?? r.created_at).getTime() >= cutoff
        ) ?? null
    )
}

/** One decile of the latest scoring run's predicted probabilities: `lower` ≤ p < `lower` + 0.1. */
/** How far back the Predictions tab looks for the latest scoring batch, so it never scans the full history. */
export const LATEST_BATCH_LOOKBACK_DAYS = 90

export interface ProbabilityBucket {
    lower: number
    users: number
}

/** Metrics stored in AutoresearchRun.metrics for validation runs. */
interface ValidationRunMetrics {
    prediction_date: string
    realized_labels_count?: number
    warning?: string
    per_model?: Record<
        string,
        {
            emitted_role?: string
            model_role: string
            n_scored: number
            n_positive?: number
            n_negative?: number
            base_rate?: number
            realized_auc?: number
            brier_score?: number
            calibration_error?: number
            lift_at_10?: number
            lift_at_20?: number
            warning?: string
        }
    >
}

/** The list endpoints page at 100 rows. Follow every page so a long-lived model shows its whole history. */
async function fetchAllPages<T>(
    fetchPage: (offset: number) => Promise<{ results: T[]; next?: string | null }>
): Promise<T[]> {
    const rows: T[] = []
    for (;;) {
        const response = await fetchPage(rows.length)
        rows.push(...response.results)
        if (!response.next || response.results.length === 0) {
            return rows
        }
    }
}

/** A decoded artifact bundle file, ready for display. */
interface ViewedArtifact {
    runId: string
    path: string
    sizeBytes: number
    /** UTF-8 text for text files; null when the file is binary (e.g. model.pkl, parquet). */
    text: string | null
}

/** Bundle paths we render inline as text; anything else is treated as binary. */
const TEXT_ARTIFACT_EXTENSIONS = ['.py', '.sql', '.yml', '.yaml', '.json', '.md', '.txt', '.ipynb', '.csv']

function isTextArtifact(path: string): boolean {
    return TEXT_ARTIFACT_EXTENSIONS.some((ext) => path.toLowerCase().endsWith(ext))
}

function base64ToUtf8(base64: string): string {
    const binary = atob(base64)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i)
    }
    return new TextDecoder('utf-8').decode(bytes)
}

/** Displayed progress for a training run. */
interface TrainingRunProgress {
    iterationCount: number
    bestHoldoutScore: number | null
}

/**
 * The persisted iteration_count and best_holdout_score are only written at completion,
 * so while a run is in flight we derive progress from the iteration rows, which land live.
 */
export function trainingRunProgress(run: AutoresearchTrainingRunApi): TrainingRunProgress {
    // Only completion writes the counters; a failed run keeps them at zero, so read its recorded iterations.
    if (run.status === 'completed') {
        return { iterationCount: run.iteration_count, bestHoldoutScore: run.best_holdout_score }
    }
    const scores = run.iterations.map((it) => it.holdout_score).filter((score): score is number => score != null)
    return {
        iterationCount: run.iterations.length,
        bestHoldoutScore: scores.length > 0 ? Math.max(...scores) : null,
    }
}

/**
 * Features in the run model's reported top drivers but not the champion's, and the reverse.
 * Each list is capped and can be partial, so a feature missing from a list can still be a model input.
 */
export interface FeatureChanges {
    added: string[]
    dropped: string[]
}

export function featureChanges(
    runExplanation: ModelExplanationFieldApi,
    championExplanation: ModelExplanationFieldApi
): FeatureChanges {
    const runNames = (runExplanation.top_features ?? []).map((f) => f.name)
    const championNames = (championExplanation.top_features ?? []).map((f) => f.name)
    // An empty list means the model recorded no importances, which says nothing about its features.
    if (runNames.length === 0 || championNames.length === 0) {
        return { added: [], dropped: [] }
    }
    return {
        added: runNames.filter((name) => !championNames.includes(name)),
        dropped: championNames.filter((name) => !runNames.includes(name)),
    }
}

/** How much of the inference population the latest scoring run covered, when it scored only part of it. */
export interface ScoringCoverage {
    scored: number
    eligible: number
    /** Days it takes to score everyone once: the runs a rotation needs times the days between runs. */
    rescoreDays: number
}

/**
 * A population at or above the scoring cap is scored on a rolling basis: each run scores the
 * people whose last score is oldest. Returns null when the latest completed run scored everyone.
 */
export function scoringCoverage(runs: AutoresearchRunApi[], cadenceDays: number): ScoringCoverage | null {
    const latest = runs
        .filter((run) => run.run_type === 'inference' && run.status === 'completed')
        .reduce<AutoresearchRunApi | null>(
            (newest, run) => (newest === null || run.created_at > newest.created_at ? run : newest),
            null
        )
    const scored = latest?.rows_scored ?? 0
    const eligible = latest?.metrics?.rows_eligible
    if (scored <= 0 || typeof eligible !== 'number' || eligible <= scored) {
        return null
    }
    return { scored, eligible, rescoreDays: Math.ceil(eligible / scored) * Math.max(cadenceDays, 1) }
}

/** One scoring day's volume: emitted prediction events and their average probability as a 0-100 percentage. */
export interface DailyVolumePoint {
    day: string
    users: number
    avgProbabilityPct: number
}

/** Flattened row for the online performance table. */
export interface OnlinePerformanceRow {
    run_id: string
    model_id: string
    prediction_date: string
    /** The role the model held when it emitted these predictions; `model_role` is its role now. */
    emitted_role: string
    model_role: string
    n_scored: number
    realized_auc: number | null
    brier_score: number | null
    calibration_error: number | null
    lift_at_10: number | null
    lift_at_20: number | null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface autoresearchPipelineLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    currentTeamId: number | null // teamLogic
    activeScoreRun: AutoresearchRunApi | null
    activeTab: AutoresearchPipelineTab
    artifactsByRun: Record<string, string[]>
    artifactsByRunLoading: boolean
    breadcrumbs: Breadcrumb[]
    champion: AutoresearchModelApi | null
    dailyVolume: DailyVolumePoint[] | null
    dailyVolumeError: boolean
    dailyVolumeLoading: boolean
    detailRequested: boolean
    expandedRunId: string | null
    modelByTrainingRun: Record<string, AutoresearchModelApi>
    models: AutoresearchModelApi[]
    modelsError: boolean
    modelsLoading: boolean
    onlinePerformanceRows: OnlinePerformanceRow[]
    pipeline: AutoresearchPipelineApi | null
    pipelineError: boolean
    pipelineLoading: boolean
    predictionsPeopleView: PredictionsPeopleView
    probabilityDistribution: ProbabilityBucket[] | null
    probabilityDistributionError: boolean
    probabilityDistributionLoading: boolean
    probabilityHistogram: ProbabilityBucket[] | null
    reportByRun: Record<string, string | null>
    reportByRunLoading: boolean
    runs: AutoresearchRunApi[]
    runsError: boolean
    runsLoading: boolean
    scoreResult: AutoresearchRunApi | null
    scoreResultLoading: boolean
    scoringCoverage: ScoringCoverage | null
    startTrainingResult: AutoresearchTrainingRunApi | null
    startTrainingResultLoading: boolean
    suggestionDraft: string
    suggestionPriority: CreateSuggestionPriorityEnumApi
    suggestionSubmitResult: AutoresearchSuggestionApi | null
    suggestionSubmitResultLoading: boolean
    suggestions: AutoresearchSuggestionApi[]
    suggestionsError: boolean
    suggestionsLoading: boolean
    trainingRuns: AutoresearchTrainingRunApi[]
    trainingRunsError: boolean
    trainingRunsLoading: boolean
    validationRuns: AutoresearchRunApi[]
    viewedArtifact: ViewedArtifact | null
    viewedArtifactLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface autoresearchPipelineLogicActions {
    setFeatureFlags: (
        flags: string[],
        variants: Record<string, boolean | string>
    ) => {
        flags: string[]
        variants: Record<string, boolean | string>
    } // featureFlagLogic
    loadCurrentTeamSuccess: (
        currentTeam: null | import('~/types').TeamPublicType,
        payload?: any
    ) => {
        currentTeam: null | import('~/types').TeamPublicType
        payload?: any
    } // teamLogic
    closeArtifact: () => any
    closeArtifactFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    closeArtifactSuccess: (
        viewedArtifact: null,
        payload?: any
    ) => {
        viewedArtifact: null
        payload?: any
    }
    loadDailyVolume: () => any
    loadDailyVolumeFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadDailyVolumeSuccess: (
        dailyVolume: {
            avgProbabilityPct: number
            day: string
            users: number
        }[],
        payload?: any
    ) => {
        dailyVolume: {
            avgProbabilityPct: number
            day: string
            users: number
        }[]
        payload?: any
    }
    loadDetail: () => {
        value: true
    }
    loadModels: () => any
    loadModelsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadModelsSuccess: (
        models: AutoresearchModelApi[],
        payload?: any
    ) => {
        models: AutoresearchModelApi[]
        payload?: any
    }
    loadPipeline: () => any
    loadPipelineFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPipelineSuccess: (
        pipeline: AutoresearchPipelineApi | null,
        payload?: any
    ) => {
        pipeline: AutoresearchPipelineApi | null
        payload?: any
    }
    loadProbabilityDistribution: () => any
    loadProbabilityDistributionFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadProbabilityDistributionSuccess: (
        probabilityDistribution: {
            lower: number
            users: number
        }[],
        payload?: any
    ) => {
        probabilityDistribution: {
            lower: number
            users: number
        }[]
        payload?: any
    }
    loadRunArtifacts: ({ runId }: { runId: string }) => {
        runId: string
    }
    loadRunArtifactsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadRunArtifactsSuccess: (
        artifactsByRun: Record<string, string[]>,
        payload?: {
            runId: string
        }
    ) => {
        artifactsByRun: Record<string, string[]>
        payload?: {
            runId: string
        }
    }
    loadRunReport: ({ runId }: { runId: string }) => {
        runId: string
    }
    loadRunReportFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadRunReportSuccess: (
        reportByRun: Record<string, string | null>,
        payload?: {
            runId: string
        }
    ) => {
        reportByRun: Record<string, string | null>
        payload?: {
            runId: string
        }
    }
    loadRuns: () => any
    loadRunsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadRunsSuccess: (
        runs: AutoresearchRunApi[],
        payload?: any
    ) => {
        runs: AutoresearchRunApi[]
        payload?: any
    }
    loadSuggestions: () => any
    loadSuggestionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSuggestionsSuccess: (
        suggestions: AutoresearchSuggestionApi[],
        payload?: any
    ) => {
        suggestions: AutoresearchSuggestionApi[]
        payload?: any
    }
    loadTrainingRuns: () => any
    loadTrainingRunsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadTrainingRunsSuccess: (
        trainingRuns: AutoresearchTrainingRunApi[],
        payload?: any
    ) => {
        trainingRuns: AutoresearchTrainingRunApi[]
        payload?: any
    }
    pausePipeline: () => any
    pausePipelineFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    pausePipelineSuccess: (
        pipeline: AutoresearchPipelineApi | null,
        payload?: any
    ) => {
        pipeline: AutoresearchPipelineApi | null
        payload?: any
    }
    pollScoreRun: () => {
        value: true
    }
    reportNotebookOpened: (runId: string) => {
        runId: string
    }
    resumePipeline: () => any
    resumePipelineFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    resumePipelineSuccess: (
        pipeline: AutoresearchPipelineApi | null,
        payload?: any
    ) => {
        pipeline: AutoresearchPipelineApi | null
        payload?: any
    }
    scoreNow: () => any
    scoreNowFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    scoreNowSuccess: (
        scoreResult: AutoresearchRunApi | null,
        payload?: any
    ) => {
        scoreResult: AutoresearchRunApi | null
        payload?: any
    }
    scoreRunFinished: (run: AutoresearchRunApi) => {
        run: AutoresearchRunApi
    }
    setActiveScoreRun: (run: AutoresearchRunApi | null) => {
        run: AutoresearchRunApi | null
    }
    setActiveTab: (tab: AutoresearchPipelineTab) => {
        tab: AutoresearchPipelineTab
    }
    setPredictionsPeopleView: (view: PredictionsPeopleView) => {
        view: PredictionsPeopleView
    }
    setSuggestionDraft: (draft: string) => {
        draft: string
    }
    setSuggestionPriority: (priority: CreateSuggestionPriorityEnumApi) => {
        priority: CreateSuggestionPriorityEnumApi
    }
    startScorePolling: () => {
        value: true
    }
    startTraining: () => any
    startTrainingFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    startTrainingSuccess: (
        startTrainingResult: AutoresearchTrainingRunApi | null,
        payload?: any
    ) => {
        startTrainingResult: AutoresearchTrainingRunApi | null
        payload?: any
    }
    submitSuggestion: () => any
    submitSuggestionFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    submitSuggestionSuccess: (
        suggestionSubmitResult: AutoresearchSuggestionApi | null,
        payload?: any
    ) => {
        suggestionSubmitResult: AutoresearchSuggestionApi | null
        payload?: any
    }
    toggleRunArtifacts: (runId: string) => {
        runId: string
    }
    viewArtifact: ({ runId, path }: { path: string; runId: string }) => {
        runId: string
        path: string
    }
    viewArtifactFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    viewArtifactSuccess: (
        viewedArtifact: {
            path: string
            runId: string
            sizeBytes: number
            text: string | null
        } | null,
        payload?: {
            runId: string
            path: string
        }
    ) => {
        viewedArtifact: {
            path: string
            runId: string
            sizeBytes: number
            text: string | null
        } | null
        payload?: {
            runId: string
            path: string
        }
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface autoresearchPipelineLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        breadcrumbs: (pipeline: AutoresearchPipelineApi | null) => Breadcrumb[]
        champion: (models: AutoresearchModelApi[]) => AutoresearchModelApi | null
        modelByTrainingRun: (models: AutoresearchModelApi[]) => Record<string, AutoresearchModelApi>
        validationRuns: (runs: AutoresearchRunApi[]) => AutoresearchRunApi[]
        scoringCoverage: (
            runs: AutoresearchRunApi[],
            pipeline: AutoresearchPipelineApi | null
        ) => ScoringCoverage | null
        onlinePerformanceRows: (validationRuns: AutoresearchRunApi[]) => OnlinePerformanceRow[]
        probabilityHistogram: (probabilityDistribution: ProbabilityBucket[] | null) => ProbabilityBucket[] | null
    }
}

export type autoresearchPipelineLogicType = MakeLogicType<
    autoresearchPipelineLogicValues,
    autoresearchPipelineLogicActions,
    AutoresearchPipelineLogicProps,
    autoresearchPipelineLogicMeta
>

export const autoresearchPipelineLogic = kea<autoresearchPipelineLogicType>([
    path((key) => ['products', 'autoresearch', 'autoresearchPipelineLogic', key]),
    props({} as AutoresearchPipelineLogicProps),
    key((props) => props.id),
    connect({
        values: [teamLogic, ['currentTeamId'], featureFlagLogic, ['featureFlags']],
        actions: [teamLogic, ['loadCurrentTeamSuccess'], featureFlagLogic, ['setFeatureFlags']],
    }),
    actions({
        setActiveTab: (tab: AutoresearchPipelineTab) => ({ tab }),
        setPredictionsPeopleView: (view: PredictionsPeopleView) => ({ view }),
        loadDetail: true,
        toggleRunArtifacts: (runId: string) => ({ runId }),
        reportNotebookOpened: (runId: string) => ({ runId }),
        setSuggestionDraft: (draft: string) => ({ draft }),
        setSuggestionPriority: (priority: CreateSuggestionPriorityEnumApi) => ({ priority }),
        setActiveScoreRun: (run: AutoresearchRunApi | null) => ({ run }),
        startScorePolling: true,
        pollScoreRun: true,
        scoreRunFinished: (run: AutoresearchRunApi) => ({ run }),
    }),
    reducers({
        detailRequested: [
            false,
            {
                loadDetail: () => true,
            },
        ],
        activeTab: [
            'overview' as AutoresearchPipelineTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        predictionsPeopleView: [
            'most_likely' as PredictionsPeopleView,
            {
                setPredictionsPeopleView: (_, { view }) => view,
            },
        ],
        activeScoreRun: [
            null as AutoresearchRunApi | null,
            {
                setActiveScoreRun: (_, { run }) => run,
                scoreNowSuccess: (_, { scoreResult }) => (scoreResult?.status === 'running' ? scoreResult : null),
                loadRunsSuccess: (current, { runs }) => current ?? findRunningScoreRun(runs),
                scoreRunFinished: () => null,
            },
        ],
        expandedRunId: [
            null as string | null,
            {
                toggleRunArtifacts: (current, { runId }) => (current === runId ? null : runId),
            },
        ],
        suggestionDraft: [
            '',
            {
                setSuggestionDraft: (_, { draft }) => draft,
                submitSuggestionSuccess: () => '',
            },
        ],
        suggestionPriority: [
            CreateSuggestionPriorityEnumApi.Consider as CreateSuggestionPriorityEnumApi,
            {
                setSuggestionPriority: (_, { priority }) => priority,
            },
        ],
        probabilityDistributionError: [
            false,
            {
                loadProbabilityDistribution: () => false,
                loadProbabilityDistributionFailure: () => true,
            },
        ],
        pipelineError: [
            false,
            {
                loadPipeline: () => false,
                loadPipelineSuccess: () => false,
                loadPipelineFailure: () => true,
            },
        ],
        modelsError: [
            false,
            {
                loadModels: () => false,
                loadModelsFailure: () => true,
            },
        ],
        trainingRunsError: [
            false,
            {
                loadTrainingRuns: () => false,
                loadTrainingRunsFailure: () => true,
            },
        ],
        runsError: [
            false,
            {
                loadRuns: () => false,
                loadRunsFailure: () => true,
            },
        ],
        suggestionsError: [
            false,
            {
                loadSuggestions: () => false,
                loadSuggestionsFailure: () => true,
            },
        ],
        dailyVolumeError: [
            false,
            {
                loadDailyVolume: () => false,
                loadDailyVolumeFailure: () => true,
            },
        ],
    }),
    loaders(({ values, props }) => ({
        pipeline: [
            null as AutoresearchPipelineApi | null,
            {
                loadPipeline: async () => {
                    if (!values.currentTeamId) {
                        return null
                    }
                    return autoresearchRetrieve(String(values.currentTeamId), props.id)
                },
                pausePipeline: async () => {
                    if (!values.currentTeamId || !values.pipeline) {
                        return values.pipeline
                    }
                    // The endpoint ignores the body (it only flips status), but the generated
                    // client types a pipeline body — pass the current one to satisfy it.
                    return autoresearchPauseCreate(String(values.currentTeamId), props.id)
                },
                resumePipeline: async () => {
                    if (!values.currentTeamId || !values.pipeline) {
                        return values.pipeline
                    }
                    return autoresearchResumeCreate(String(values.currentTeamId), props.id)
                },
            },
        ],
        models: [
            [] as AutoresearchModelApi[],
            {
                loadModels: async () => {
                    if (!values.currentTeamId) {
                        return []
                    }
                    const teamId = String(values.currentTeamId)
                    return fetchAllPages((offset) => autoresearchModelsList(teamId, props.id, { offset }))
                },
            },
        ],
        trainingRuns: [
            [] as AutoresearchTrainingRunApi[],
            {
                loadTrainingRuns: async () => {
                    if (!values.currentTeamId) {
                        return []
                    }
                    const teamId = String(values.currentTeamId)
                    return fetchAllPages((offset) => autoresearchTrainingRunsList(teamId, props.id, { offset }))
                },
            },
        ],
        runs: [
            [] as AutoresearchRunApi[],
            {
                loadRuns: async () => {
                    if (!values.currentTeamId) {
                        return []
                    }
                    const teamId = String(values.currentTeamId)
                    return fetchAllPages((offset) => autoresearchRunsList(teamId, props.id, { offset }))
                },
            },
        ],
        suggestions: [
            [] as AutoresearchSuggestionApi[],
            {
                loadSuggestions: async () => {
                    if (!values.currentTeamId) {
                        return []
                    }
                    const teamId = String(values.currentTeamId)
                    return fetchAllPages((offset) => autoresearchSuggestionsList(teamId, props.id, { offset }))
                },
            },
        ],
        startTrainingResult: [
            null as AutoresearchTrainingRunApi | null,
            {
                startTraining: async () => {
                    if (!values.currentTeamId) {
                        return null
                    }
                    const result = await autoresearchTrainCreate(String(values.currentTeamId), props.id)
                    return result
                },
            },
        ],
        artifactsByRun: [
            {} as Record<string, string[]>,
            {
                loadRunArtifacts: async ({ runId }: { runId: string }) => {
                    if (!values.currentTeamId) {
                        return values.artifactsByRun
                    }
                    const response = await autoresearchTrainingRunsArtifactsRetrieve(
                        String(values.currentTeamId),
                        props.id,
                        runId
                    )
                    return { ...values.artifactsByRun, [runId]: response.paths }
                },
            },
        ],
        reportByRun: [
            {} as Record<string, string | null>,
            {
                // A run's report.md, decoded to text. null = loaded but the agent uploaded no report.
                loadRunReport: async ({ runId }: { runId: string }) => {
                    if (!values.currentTeamId) {
                        return values.reportByRun
                    }
                    try {
                        const response = await autoresearchTrainingRunsArtifactsGetCreate(
                            String(values.currentTeamId),
                            props.id,
                            runId,
                            { path: 'report.md' }
                        )
                        return { ...values.reportByRun, [runId]: base64ToUtf8(response.content_base64) }
                    } catch {
                        return { ...values.reportByRun, [runId]: null }
                    }
                },
            },
        ],
        viewedArtifact: [
            null as ViewedArtifact | null,
            {
                viewArtifact: async ({ runId, path }: { runId: string; path: string }) => {
                    if (!values.currentTeamId) {
                        return null
                    }
                    const response = await autoresearchTrainingRunsArtifactsGetCreate(
                        String(values.currentTeamId),
                        props.id,
                        runId,
                        { path }
                    )
                    return {
                        runId,
                        path: response.path,
                        sizeBytes: response.size_bytes,
                        text: isTextArtifact(response.path) ? base64ToUtf8(response.content_base64) : null,
                    }
                },
                closeArtifact: () => null,
            },
        ],
        scoreResult: [
            null as AutoresearchRunApi | null,
            {
                scoreNow: async () => {
                    if (!values.currentTeamId) {
                        return null
                    }
                    return autoresearchScoreCreate(String(values.currentTeamId), props.id)
                },
            },
        ],
        probabilityDistribution: [
            null as ProbabilityBucket[] | null,
            {
                loadProbabilityDistribution: async () => {
                    // Capture can shift the timestamps of one batch apart, so the latest batch is its prediction date.
                    const response = await api.queryHogQL(
                        hogql`
                            SELECT least(floor(p * 10), 9) AS bucket, count() AS users
                            FROM (
                                SELECT
                                    coalesce(nullIf(properties.$autoresearch_person_id, ''), distinct_id) AS person_id,
                                    argMax(toFloat(properties.$autoresearch_p_y), timestamp) AS p
                                FROM events
                                WHERE event = 'autoresearch_prediction'
                                  AND properties.$autoresearch_pipeline_id = ${props.id}
                                  AND timestamp >= now() - INTERVAL ${LATEST_BATCH_LOOKBACK_DAYS} DAY
                                  AND properties.$autoresearch_prediction_date = (
                                      SELECT max(properties.$autoresearch_prediction_date)
                                      FROM events
                                      WHERE event = 'autoresearch_prediction'
                                        AND properties.$autoresearch_pipeline_id = ${props.id}
                                        AND timestamp >= now() - INTERVAL ${LATEST_BATCH_LOOKBACK_DAYS} DAY
                                  )
                                GROUP BY person_id
                            )
                            GROUP BY bucket
                            ORDER BY bucket
                        `,
                        { productKey: 'autoresearch', name: 'autoresearch_probability_distribution' }
                    )
                    return (response.results ?? []).map((row: any[]) => ({
                        lower: Number(row[0]) / 10,
                        users: Number(row[1]),
                    }))
                },
            },
        ],
        dailyVolume: [
            null as DailyVolumePoint[] | null,
            {
                loadDailyVolume: async () => {
                    // The last 60 days, returned oldest-first for left-to-right display. The time bound keeps the scan off the full history.
                    const response = await api.queryHogQL(
                        hogql`
                            SELECT toDate(timestamp) AS day,
                                   count() AS users_scored,
                                   round(100 * avg(toFloat(properties.$autoresearch_p_y)), 1) AS avg_probability
                            FROM events
                            WHERE event = 'autoresearch_prediction'
                              AND properties.$autoresearch_pipeline_id = ${props.id}
                              AND timestamp >= now() - INTERVAL 60 DAY
                            GROUP BY day
                            ORDER BY day DESC
                            LIMIT 60
                        `,
                        { productKey: 'autoresearch', name: 'autoresearch_daily_volume' }
                    )
                    return (response.results ?? [])
                        .map((row: any[]) => ({
                            day: String(row[0]),
                            users: Number(row[1]),
                            avgProbabilityPct: Number(row[2]),
                        }))
                        .reverse()
                },
            },
        ],
        suggestionSubmitResult: [
            null as AutoresearchSuggestionApi | null,
            {
                submitSuggestion: async () => {
                    if (!values.currentTeamId || !values.suggestionDraft.trim()) {
                        return null
                    }
                    return autoresearchSuggestionsCreate(String(values.currentTeamId), props.id, {
                        prompt: values.suggestionDraft.trim(),
                        priority: values.suggestionPriority,
                    })
                },
            },
        ],
    })),
    selectors({
        breadcrumbs: [
            (s) => [s.pipeline],
            (pipeline: AutoresearchPipelineApi | null): Breadcrumb[] => [
                {
                    key: Scene.Autoresearch,
                    name: 'Autoresearch',
                    path: urls.autoresearch(),
                },
                {
                    key: [Scene.AutoresearchPipeline, pipeline?.id ?? 'unknown'],
                    name: pipeline?.name ?? 'Model',
                },
            ],
        ],
        champion: [
            (s) => [s.models],
            (models: AutoresearchModelApi[]): AutoresearchModelApi | null =>
                models.find((m) => m.role === AutoresearchModelRoleEnumApi.Champion) ?? null,
        ],
        modelByTrainingRun: [
            (s) => [s.models],
            (models: AutoresearchModelApi[]): Record<string, AutoresearchModelApi> =>
                Object.fromEntries(
                    models.filter((m) => m.source_training_run).map((m) => [m.source_training_run as string, m])
                ),
        ],
        validationRuns: [
            (s) => [s.runs],
            (runs: AutoresearchRunApi[]): AutoresearchRunApi[] =>
                runs.filter((r) => r.run_type === 'validation' && r.status === 'completed'),
        ],
        scoringCoverage: [
            (s) => [s.runs, s.pipeline],
            (runs: AutoresearchRunApi[], pipeline: AutoresearchPipelineApi | null): ScoringCoverage | null =>
                scoringCoverage(runs, pipeline?.cadence_days ?? 1),
        ],
        onlinePerformanceRows: [
            (s) => [s.validationRuns],
            (validationRuns: AutoresearchRunApi[]): OnlinePerformanceRow[] => {
                const rows: OnlinePerformanceRow[] = []
                for (const run of validationRuns) {
                    const m = run.metrics as Partial<ValidationRunMetrics> | null
                    if (!m?.prediction_date) {
                        continue
                    }
                    if (!m.per_model || Object.keys(m.per_model).length === 0) {
                        continue
                    }
                    for (const [modelId, model] of Object.entries(m.per_model)) {
                        rows.push({
                            run_id: run.id,
                            model_id: modelId,
                            prediction_date: m.prediction_date,
                            emitted_role: model.emitted_role ?? model.model_role,
                            model_role: model.model_role,
                            n_scored: model.n_scored,
                            realized_auc: model.realized_auc ?? null,
                            brier_score: model.brier_score ?? null,
                            calibration_error: model.calibration_error ?? null,
                            lift_at_10: model.lift_at_10 ?? null,
                            lift_at_20: model.lift_at_20 ?? null,
                        })
                    }
                }
                // Sort by date descending, champion before challenger within same date
                rows.sort((a, b) => {
                    if (b.prediction_date !== a.prediction_date) {
                        return b.prediction_date.localeCompare(a.prediction_date)
                    }
                    return a.emitted_role === 'champion' ? -1 : 1
                })
                return rows
            },
        ],
        probabilityHistogram: [
            (s) => [s.probabilityDistribution],
            (probabilityDistribution: ProbabilityBucket[] | null): ProbabilityBucket[] | null => {
                if (!probabilityDistribution) {
                    return null
                }
                const usersByDecile = new Map(probabilityDistribution.map((b) => [Math.round(b.lower * 10), b.users]))
                return Array.from({ length: 10 }, (_, decile) => ({
                    lower: decile / 10,
                    users: usersByDecile.get(decile) ?? 0,
                }))
            },
        ],
    }),
    listeners(({ actions, values, props, cache }) => ({
        loadDetail: () => {
            actions.loadPipeline()
            actions.loadModels()
            actions.loadTrainingRuns()
            actions.loadRuns()
            actions.loadSuggestions()
        },
        loadCurrentTeamSuccess: () => {
            if (values.featureFlags[FEATURE_FLAGS.AUTORESEARCH]) {
                actions.loadDetail()
            }
        },
        setFeatureFlags: () => {
            // Flags can arrive after mount, when afterMount already skipped the load. Start it once the flag is on.
            if (values.featureFlags[FEATURE_FLAGS.AUTORESEARCH] && !values.detailRequested) {
                posthog.capture('autoresearch model viewed', { pipeline_id: props.id })
                actions.loadDetail()
            }
        },
        loadPipelineFailure: () => {
            posthog.capture('autoresearch model load failed', { pipeline_id: props.id })
        },
        loadPipelineSuccess: ({ pipeline }) => {
            // The prediction-event queries are only worth running once the pipeline has ever scored.
            if (pipeline?.last_scored_at && !values.probabilityDistribution && !values.probabilityDistributionLoading) {
                actions.loadProbabilityDistribution()
            }
            if (pipeline?.last_scored_at && !values.dailyVolume && !values.dailyVolumeLoading) {
                actions.loadDailyVolume()
            }
        },
        startTrainingSuccess: () => {
            posthog.capture('autoresearch model training started', { pipeline_id: props.id })
            actions.loadTrainingRuns()
            actions.loadPipeline()
            lemonToast.success('Training run started')
        },
        startTrainingFailure: () => {
            posthog.capture('autoresearch model action failed', { action: 'train', pipeline_id: props.id })
            lemonToast.error('Could not start training run')
        },
        pausePipelineSuccess: () => {
            posthog.capture('autoresearch model paused', { pipeline_id: props.id })
            lemonToast.success('Model paused. Scheduled scoring is on hold.')
        },
        pausePipelineFailure: () => {
            posthog.capture('autoresearch model action failed', { action: 'pause', pipeline_id: props.id })
            lemonToast.error('Could not pause the model')
        },
        resumePipelineSuccess: () => {
            posthog.capture('autoresearch model resumed', { pipeline_id: props.id })
            lemonToast.success('Model resumed')
        },
        resumePipelineFailure: () => {
            posthog.capture('autoresearch model action failed', { action: 'resume', pipeline_id: props.id })
            lemonToast.error('Could not resume the model')
        },
        scoreNowSuccess: ({ scoreResult }) => {
            if (!scoreResult) {
                return
            }
            posthog.capture('autoresearch model score started', { pipeline_id: props.id, run_id: scoreResult.id })
            if (scoreResult.status === 'running') {
                lemonToast.info('Scoring started. Predictions update when it finishes.')
                actions.startScorePolling()
            } else {
                actions.scoreRunFinished(scoreResult)
            }
        },
        scoreNowFailure: ({ error }) => {
            posthog.capture('autoresearch model action failed', { action: 'score', pipeline_id: props.id })
            lemonToast.error(error ? `Could not start scoring. ${error}` : 'Could not start scoring. Try again.')
        },
        loadRunsSuccess: () => {
            // A run started before a reload, or by the daily schedule, is still followed to the end.
            if (values.activeScoreRun) {
                actions.startScorePolling()
            }
        },
        startScorePolling: () => {
            if (cache.disposables.registry.has('scorePoll')) {
                return
            }
            cache.disposables.add(() => {
                const timer = window.setInterval(() => actions.pollScoreRun(), SCORE_RUN_POLL_INTERVAL_MS)
                return () => clearInterval(timer)
            }, 'scorePoll')
        },
        pollScoreRun: async () => {
            const active = values.activeScoreRun
            if (!values.currentTeamId || !active) {
                cache.disposables.dispose('scorePoll')
                return
            }
            let run: AutoresearchRunApi
            try {
                run = await autoresearchRunsRetrieve(String(values.currentTeamId), props.id, active.id)
            } catch {
                // A failed check is retried on the next interval.
                return
            }
            if (isScoreRunInProgress(run)) {
                return
            }
            actions.scoreRunFinished(run)
        },
        scoreRunFinished: ({ run }) => {
            cache.disposables.dispose('scorePoll')
            actions.loadRuns()
            actions.loadPipeline()
            if (run.status === 'completed') {
                posthog.capture('autoresearch model scored', {
                    pipeline_id: props.id,
                    run_id: run.id,
                    rows_scored: run.rows_scored,
                })
                actions.loadProbabilityDistribution()
                actions.loadDailyVolume()
                const scored = run.rows_scored ?? 0
                lemonToast.success(`Scored ${scored.toLocaleString()} users`)
            } else {
                posthog.capture('autoresearch model action failed', {
                    action: 'score',
                    stage: 'run',
                    pipeline_id: props.id,
                    run_id: run.id,
                })
                lemonToast.error(
                    run.error
                        ? `Scoring failed. ${run.error}`
                        : 'Scoring failed. Try again, and contact support if it keeps happening.'
                )
            }
        },
        submitSuggestionSuccess: () => {
            posthog.capture('autoresearch model suggestion sent', { pipeline_id: props.id })
            actions.loadSuggestions()
            lemonToast.success('Suggestion sent. The agent will pick it up on its next run.')
        },
        submitSuggestionFailure: () => {
            posthog.capture('autoresearch model action failed', { action: 'suggest', pipeline_id: props.id })
            lemonToast.error('Could not submit the suggestion')
        },
        toggleRunArtifacts: ({ runId }) => {
            // Lazy-load a run's bundle and report the first time it's expanded.
            if (values.expandedRunId === runId) {
                if (!values.artifactsByRun[runId]) {
                    actions.loadRunArtifacts({ runId })
                }
                if (values.reportByRun[runId] === undefined) {
                    actions.loadRunReport({ runId })
                }
            }
        },
        reportNotebookOpened: ({ runId }) => {
            posthog.capture('autoresearch model report notebook opened', { pipeline_id: props.id, run_id: runId })
        },
        setPredictionsPeopleView: ({ view }) => {
            posthog.capture('autoresearch model predictions view changed', { pipeline_id: props.id, view })
        },
    })),
    actionToUrl(({ values }) => ({
        // Reflect the active tab in the URL (?tab=…) so each tab is deep-linkable.
        setActiveTab: ({ tab }) => {
            const searchParams = { ...router.values.searchParams }
            if (tab === 'overview') {
                delete searchParams.tab
            } else {
                searchParams.tab = tab
            }
            if ((router.values.searchParams.tab ?? 'overview') === (values.activeTab as string)) {
                return // no-op when the URL already matches (avoids a redundant history entry)
            }
            return [router.values.location.pathname, searchParams, router.values.hashParams]
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/autoresearch/:id': (_, searchParams) => {
            const tab = isPipelineTab(searchParams.tab) ? searchParams.tab : 'overview'
            if (tab !== values.activeTab) {
                actions.setActiveTab(tab)
            }
        },
    })),
    afterMount(({ actions, values, props }) => {
        // With the flag off the scene shows NotFound, so there is nothing to record or load.
        if (values.featureFlags[FEATURE_FLAGS.AUTORESEARCH]) {
            posthog.capture('autoresearch model viewed', { pipeline_id: props.id })
            actions.loadDetail()
        }
    }),
])
