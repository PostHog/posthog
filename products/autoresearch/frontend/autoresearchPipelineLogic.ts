import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import type { autoresearchPipelineLogicType } from './autoresearchPipelineLogicType'
import {
    autoresearchModelsList,
    autoresearchRetrieve,
    autoresearchRunsList,
    autoresearchSuggestionsList,
    autoresearchTrainingRunsList,
    autoresearchTrainCreate,
} from './generated/api'
import type {
    AutoresearchModelApi,
    AutoresearchPipelineApi,
    AutoresearchRunApi,
    AutoresearchSuggestionApi,
    AutoresearchTrainingRunApi,
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
    | 'runs'
    | 'settings'

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
    }),
    reducers({
        activeTab: [
            'overview' as AutoresearchPipelineTab,
            {
                setActiveTab: (_, { tab }) => tab,
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
    })),
    selectors({
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
    listeners(({ actions }) => ({
        startTrainingSuccess: () => {
            actions.loadTrainingRuns()
            actions.loadPipeline()
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
