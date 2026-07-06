import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { autoresearchPipelineLogicType } from './autoresearchPipelineLogicType'
import {
    autoresearchModelsList,
    autoresearchPauseCreate,
    autoresearchResumeCreate,
    autoresearchRetrieve,
    autoresearchRunsList,
    autoresearchScoreCreate,
    autoresearchSuggestionsCreate,
    autoresearchSuggestionsList,
    autoresearchTrainingRunsArtifactsGetCreate,
    autoresearchTrainingRunsArtifactsRetrieve,
    autoresearchTrainingRunsList,
    autoresearchTrainCreate,
} from './generated/api'
import {
    type AutoresearchModelApi,
    type AutoresearchPipelineApi,
    type AutoresearchRunApi,
    type AutoresearchSuggestionApi,
    type AutoresearchTrainingRunApi,
    CreateSuggestionPriorityEnumApi,
} from './generated/api.schemas'

export interface AutoresearchPipelineLogicProps {
    id: string
}

export type AutoresearchPipelineTab =
    | 'overview'
    | 'training'
    | 'models'
    | 'predictions'
    | 'online_performance'
    | 'suggestions'
    | 'settings'

const AUTORESEARCH_PIPELINE_TABS: AutoresearchPipelineTab[] = [
    'overview',
    'training',
    'models',
    'predictions',
    'online_performance',
    'suggestions',
    'settings',
]

function isPipelineTab(value: string | undefined): value is AutoresearchPipelineTab {
    return value !== undefined && (AUTORESEARCH_PIPELINE_TABS as string[]).includes(value)
}

/** Metrics stored in AutoresearchRun.metrics for validation runs. */
export interface ValidationRunMetrics {
    prediction_date: string
    realized_labels_count?: number
    warning?: string
    per_model?: Record<
        string,
        {
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

/** A decoded artifact bundle file, ready for display. */
export interface ViewedArtifact {
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

/** Flattened row for the online performance table. */
export interface OnlinePerformanceRow {
    run_id: string
    prediction_date: string
    model_role: string
    n_scored: number
    realized_auc: number | null
    brier_score: number | null
    calibration_error: number | null
    lift_at_10: number | null
    lift_at_20: number | null
}

export const autoresearchPipelineLogic = kea<autoresearchPipelineLogicType>([
    path(['products', 'autoresearch', 'autoresearchPipelineLogic']),
    props({} as AutoresearchPipelineLogicProps),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    actions({
        setActiveTab: (tab: AutoresearchPipelineTab) => ({ tab }),
        toggleRunArtifacts: (runId: string) => ({ runId }),
        setSuggestionDraft: (draft: string) => ({ draft }),
        setSuggestionPriority: (priority: CreateSuggestionPriorityEnumApi) => ({ priority }),
    }),
    reducers({
        activeTab: [
            'overview' as AutoresearchPipelineTab,
            {
                setActiveTab: (_, { tab }) => tab,
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
                    return autoresearchPauseCreate(String(values.currentTeamId), props.id, values.pipeline)
                },
                resumePipeline: async () => {
                    if (!values.currentTeamId || !values.pipeline) {
                        return values.pipeline
                    }
                    return autoresearchResumeCreate(String(values.currentTeamId), props.id, values.pipeline)
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
                    const response = await autoresearchModelsList(String(values.currentTeamId), props.id)
                    return response.results
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
                    const response = await autoresearchTrainingRunsList(String(values.currentTeamId), props.id)
                    return response.results
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
                    const response = await autoresearchRunsList(String(values.currentTeamId), props.id)
                    return response.results
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
                    const response = await autoresearchSuggestionsList(String(values.currentTeamId), props.id)
                    return response.results
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
            (pipeline): Breadcrumb[] => [
                {
                    key: Scene.Autoresearch,
                    name: 'Autoresearch',
                    path: urls.autoresearch(),
                },
                {
                    key: [Scene.AutoresearchPipeline, pipeline?.id ?? 'unknown'],
                    name: pipeline?.name ?? 'Pipeline',
                },
            ],
        ],
        validationRuns: [
            (s) => [s.runs],
            (runs): AutoresearchRunApi[] => runs.filter((r) => r.run_type === 'validation' && r.status === 'completed'),
        ],
        onlinePerformanceRows: [
            (s) => [s.validationRuns],
            (validationRuns): OnlinePerformanceRow[] => {
                const rows: OnlinePerformanceRow[] = []
                for (const run of validationRuns) {
                    const m = run.metrics as ValidationRunMetrics | null
                    if (!m?.prediction_date) {
                        continue
                    }
                    if (!m.per_model || Object.keys(m.per_model).length === 0) {
                        continue
                    }
                    for (const [, model] of Object.entries(m.per_model)) {
                        rows.push({
                            run_id: run.id,
                            prediction_date: m.prediction_date,
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
                    return a.model_role === 'champion' ? -1 : 1
                })
                return rows
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        startTrainingSuccess: () => {
            actions.loadTrainingRuns()
            actions.loadPipeline()
            lemonToast.success('Training run started')
        },
        startTrainingFailure: () => {
            lemonToast.error('Could not start training run')
        },
        pausePipelineSuccess: () => {
            lemonToast.success('Pipeline paused — daily scoring is on hold')
        },
        pausePipelineFailure: () => {
            lemonToast.error('Could not pause the pipeline')
        },
        resumePipelineSuccess: () => {
            lemonToast.success('Pipeline resumed')
        },
        resumePipelineFailure: () => {
            lemonToast.error('Could not resume the pipeline')
        },
        scoreNowSuccess: ({ scoreResult }) => {
            actions.loadRuns()
            actions.loadPipeline()
            const scored = scoreResult?.rows_scored
            lemonToast.success(scored != null ? `Scored ${scored.toLocaleString()} users` : 'Scoring run started')
        },
        scoreNowFailure: () => {
            lemonToast.error('Could not score users — train a champion model first')
        },
        submitSuggestionSuccess: () => {
            actions.loadSuggestions()
            lemonToast.success('Suggestion sent — the agent will pick it up on its next run')
        },
        submitSuggestionFailure: () => {
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
    afterMount(({ actions }) => {
        actions.loadPipeline()
        actions.loadModels()
        actions.loadTrainingRuns()
        actions.loadRuns()
        actions.loadSuggestions()
    }),
])
