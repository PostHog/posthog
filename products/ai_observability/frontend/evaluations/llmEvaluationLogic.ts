import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { signalSourcesLogic } from 'scenes/inbox/signalSourcesLogic'
import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from 'scenes/inbox/types'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { MaxContextInput, createMaxContextHelpers } from '~/scenes/max/maxTypes'
import { Breadcrumb } from '~/types'

import { parseTrialProviderKeyId } from '../ModelPicker'
import { LLMProviderKey, llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import { getUnhealthyProviderKey } from '../settings/providerKeyStateUtils'
import { queryEvaluationRuns } from '../utils'
import { evaluationErrorMessage } from './apiErrors'
import { EVALUATION_SUMMARY_MAX_RUNS } from './constants'
import {
    evaluationCanResolveModel,
    evaluationSupportsReports,
    evaluationTypeDefaultsToBooleanOutput,
    isBooleanEvaluationOutput,
    isLLMJudgeEvaluation,
} from './evaluationCapabilities'
import { evaluationReportLogic, persistReportDraft } from './evaluationReportLogic'
import type { llmEvaluationLogicType } from './llmEvaluationLogicType'
import { EvaluationTemplateKey, defaultEvaluationTemplates } from './templates'
import type {
    EvaluationConditionSet,
    EvaluationConfig,
    EvaluationRun,
    EvaluationSummary,
    EvaluationSummaryFilter,
    EvaluationTarget,
    EvaluationType,
    HogEvaluation,
    LLMJudgeEvaluation,
    HogTestResult,
    ModelConfiguration,
    SentimentEvaluation,
} from './types'

// Mirrors TRACE_EVAL_DEFAULT_WINDOW_SECONDS on the backend — the value pre-filled when an
// evaluation is switched to the trace target. The backend re-defaults and clamps regardless.
export const DEFAULT_TRACE_WINDOW_SECONDS = 30 * 60

export const DEFAULT_HOG_SOURCE = `// Check that the output is not empty
let result := length(output) > 0
if (not result) {
    print('Output is empty')
}
return result`

// Trace Hog globals expose `events` and `trace`, not a top-level `output`, so the generation
// default can't run against them — seed a trace-shaped check instead.
export const DEFAULT_TRACE_HOG_SOURCE = `// Check that the trace produced at least one event
let result := length(events) > 0
if (not result) {
    print('Trace has no events')
}
return result`

const DEFAULT_SENTIMENT_SOURCE = 'user_messages' as const
const DEFAULT_SENTIMENT_RUNS_FILTER = 'negative' as const
const DEFAULT_CONDITION_ROLLOUT_PERCENTAGE = 100

function toLLMJudgeEvaluation(evaluation: EvaluationConfig): LLMJudgeEvaluation {
    return {
        ...evaluation,
        evaluation_type: 'llm_judge',
        evaluation_config: { prompt: '' },
        output_type: 'boolean',
        output_config: { allows_na: false },
    }
}

function toHogEvaluation(evaluation: EvaluationConfig): HogEvaluation {
    return {
        ...evaluation,
        evaluation_type: 'hog',
        evaluation_config: { source: evaluation.target === 'trace' ? DEFAULT_TRACE_HOG_SOURCE : DEFAULT_HOG_SOURCE },
        output_type: 'boolean',
        model_configuration: null,
        output_config: { ...evaluation.output_config, allows_na: false },
    }
}

function toSentimentEvaluation(evaluation: EvaluationConfig): SentimentEvaluation {
    return {
        ...evaluation,
        evaluation_type: 'sentiment',
        evaluation_config: { source: DEFAULT_SENTIMENT_SOURCE },
        output_type: 'sentiment',
        output_config: {},
        model_configuration: null,
        // Sentiment is per-message within a single generation; a trace target is unsupported.
        target: 'generation',
        target_config: {},
    }
}

function filterEvaluationRuns(runs: EvaluationRun[], filter: EvaluationSummaryFilter): EvaluationRun[] {
    if (filter === 'all') {
        return runs
    }

    const completedRuns = runs.filter((r) => r.status === 'completed')
    if (filter === 'pass') {
        return completedRuns.filter((r) => r.result === true)
    }
    if (filter === 'fail') {
        return completedRuns.filter((r) => r.result === false)
    }
    if (filter === 'na') {
        return completedRuns.filter((r) => r.result === null)
    }

    return completedRuns.filter((r) => r.sentiment_label?.toLowerCase() === filter)
}

export interface LLMEvaluationLogicProps {
    evaluationId: string
    templateKey?: EvaluationTemplateKey
    evaluationType?: EvaluationType
}

export const llmEvaluationLogic = kea<llmEvaluationLogicType>([
    path(['products', 'ai_observability', 'evaluations', 'llmEvaluationLogic']),
    props({} as LLMEvaluationLogicProps),
    key(
        (props) =>
            `${props.evaluationId || 'new'}${props.templateKey ? `-${props.templateKey}` : ''}${
                props.evaluationType ? `-${props.evaluationType}` : ''
            }`
    ),

    connect(() => ({
        values: [
            llmProviderKeysLogic,
            ['providerKeys', 'providerKeysLoading', 'requiresProviderKey', 'isTrialGrandfathered'],
            signalSourcesLogic,
            ['sourceConfigs', 'sourceConfigsLoading'],
        ],
        actions: [
            llmProviderKeysLogic,
            ['loadProviderKeys', 'loadEvaluationConfigSuccess'],
            signalSourcesLogic,
            [
                'loadSourceConfigs',
                'loadSourceConfigsSuccess',
                'toggleSignalSource',
                'toggleSignalSourceSuccess',
                'toggleSignalSourceFailure',
            ],
        ],
    })),

    actions({
        // Evaluation configuration actions
        setEvaluationName: (name: string) => ({ name }),
        setEvaluationDescription: (description: string) => ({ description }),
        setEvaluationPrompt: (prompt: string) => ({ prompt }),
        setEvaluationEnabled: (enabled: boolean) => ({ enabled }),
        setAllowsNA: (allowsNA: boolean) => ({ allowsNA }),
        setTriggerConditions: (conditions: EvaluationConditionSet[]) => ({ conditions }),
        setModelConfiguration: (modelConfiguration: ModelConfiguration | null) => ({ modelConfiguration }),
        setEvaluationType: (evaluationType: EvaluationType) => ({ evaluationType }),
        setEvaluationTarget: (target: EvaluationTarget) => ({ target }),
        setTraceWindowSeconds: (windowSeconds: number) => ({ windowSeconds }),
        setHogSource: (source: string) => ({ source }),

        // Signal emission
        setSignalEmission: (enabled: boolean) => ({ enabled }),

        // Tab navigation
        setActiveTab: (tab: string) => ({ tab }),

        // Evaluation management actions
        saveEvaluation: true,
        saveEvaluationSuccess: (evaluation: EvaluationConfig) => ({ evaluation }),
        saveEvaluationFailure: (error: string) => ({ error }),
        loadEvaluation: true,
        loadEvaluationSuccess: (evaluation: EvaluationConfig | null) => ({ evaluation }),
        resetEvaluation: true,

        // Evaluation runs actions
        refreshEvaluationRuns: true,

        // Model selection actions
        selectModelFromPicker: (modelId: string, providerKeyId: string) => ({ modelId, providerKeyId }),

        // Hog test actions
        clearHogTestResults: true,

        // Evaluation summary actions
        setEvaluationSummaryFilter: (filter: EvaluationSummaryFilter, previousFilter: EvaluationSummaryFilter) => ({
            filter,
            previousFilter,
        }),
        toggleSummaryExpanded: true,
        regenerateEvaluationSummary: true,
        trackSummarizeClicked: true,
    }),

    loaders(({ props, values }) => ({
        hogTestResults: [
            null as HogTestResult[] | null,
            {
                testHogOnSample: async (): Promise<HogTestResult[] | null> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    const evaluation = values.evaluation
                    if (!evaluation || evaluation.evaluation_type !== 'hog') {
                        return null
                    }
                    try {
                        const conditions = evaluation.conditions
                            .filter((c) => c.properties && c.properties.length > 0)
                            .map((c) => ({ properties: c.properties }))
                        // nosemgrep: prefer-codegen-api
                        const response = await api.create(`/api/environments/${teamId}/evaluations/test_hog/`, {
                            source: evaluation.evaluation_config.source,
                            sample_count: 5,
                            allows_na: evaluation.output_config?.allows_na ?? false,
                            conditions,
                        })
                        return response.results
                    } catch (e: unknown) {
                        const message = e instanceof Error ? e.message : typeof e === 'string' ? e : 'Unknown error'
                        return [
                            {
                                event_uuid: 'error',
                                input_preview: '',
                                output_preview: '',
                                result: null,
                                reasoning: '',
                                error: typeof message === 'string' ? message : JSON.stringify(message),
                            },
                        ]
                    }
                },
            },
        ],
        evaluationRuns: [
            [] as EvaluationRun[],
            {
                loadEvaluationRuns: async () => {
                    if (!props.evaluationId || props.evaluationId === 'new') {
                        return []
                    }

                    return await queryEvaluationRuns({
                        evaluationId: props.evaluationId,
                        forceRefresh: values.isForceRefresh,
                    })
                },
            },
        ],
        evaluationSummary: [
            null as EvaluationSummary | null,
            {
                generateEvaluationSummary: async ({ forceRefresh }: { forceRefresh?: boolean }) => {
                    const shouldRefresh = forceRefresh ?? false
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId || !props.evaluationId || props.evaluationId === 'new') {
                        return null
                    }
                    if (!evaluationSupportsReports(values.evaluation)) {
                        return null
                    }

                    const requestFilter = values.evaluationSummaryFilter

                    // Backend fetches data server-side by ID - we just pass the filter
                    // nosemgrep: prefer-codegen-api
                    const response = await api.create(`/api/environments/${teamId}/llm_analytics/evaluation_summary/`, {
                        evaluation_id: props.evaluationId,
                        filter: requestFilter,
                        force_refresh: shouldRefresh,
                    })

                    // Discard if the user changed the filter while the request was in flight
                    if (values.evaluationSummaryFilter !== requestFilter) {
                        return null
                    }

                    return response as EvaluationSummary
                },
            },
        ],
    })),

    reducers({
        originalEvaluation: [
            null as EvaluationConfig | null,
            {
                loadEvaluationSuccess: (_, { evaluation }) => evaluation,
                saveEvaluationSuccess: (_, { evaluation }) => evaluation,
            },
        ],
        evaluation: [
            null as EvaluationConfig | null,
            {
                setEvaluationName: (state, { name }) => (state ? { ...state, name } : null),
                setEvaluationDescription: (state, { description }) => (state ? { ...state, description } : null),
                setEvaluationPrompt: (state, { prompt }) =>
                    state && isLLMJudgeEvaluation(state)
                        ? { ...state, evaluation_config: { ...state.evaluation_config, prompt } }
                        : state,
                setEvaluationEnabled: (state, { enabled }) => (state ? { ...state, enabled } : null),
                setAllowsNA: (state, { allowsNA }) =>
                    state && isBooleanEvaluationOutput(state.output_type)
                        ? { ...state, output_config: { ...state.output_config, allows_na: allowsNA } }
                        : state,
                setTriggerConditions: (state, { conditions }) =>
                    state
                        ? {
                              ...state,
                              conditions: conditions.map((c) =>
                                  c.rollout_percentage != null
                                      ? { ...c, rollout_percentage: Math.round(c.rollout_percentage * 100) / 100 }
                                      : c
                              ),
                          }
                        : null,
                setModelConfiguration: (state, { modelConfiguration }) =>
                    state && isLLMJudgeEvaluation(state)
                        ? { ...state, model_configuration: modelConfiguration }
                        : state,
                setEvaluationType: (state, { evaluationType }) => {
                    if (!state) {
                        return null
                    }
                    if (evaluationType === 'hog') {
                        return toHogEvaluation(state)
                    }
                    if (evaluationType === 'sentiment') {
                        return toSentimentEvaluation(state)
                    }
                    return toLLMJudgeEvaluation(state)
                },
                setEvaluationTarget: (state, { target }) => {
                    if (!state) {
                        return null
                    }
                    // Seed the window when switching to trace so the field shows a sane default;
                    // clear the bag when switching back so we don't persist a stale window.
                    const target_config = target === 'trace' ? { window_seconds: DEFAULT_TRACE_WINDOW_SECONDS } : {}
                    // Swap the default Hog source to match the new target, but only while it's still the
                    // untouched default for the other target — never clobber a source the user edited.
                    if (state.evaluation_type === 'hog') {
                        const source = state.evaluation_config.source
                        if (target === 'trace' && source === DEFAULT_HOG_SOURCE) {
                            return {
                                ...state,
                                target,
                                target_config,
                                evaluation_config: { ...state.evaluation_config, source: DEFAULT_TRACE_HOG_SOURCE },
                            }
                        }
                        if (target !== 'trace' && source === DEFAULT_TRACE_HOG_SOURCE) {
                            return {
                                ...state,
                                target,
                                target_config,
                                evaluation_config: { ...state.evaluation_config, source: DEFAULT_HOG_SOURCE },
                            }
                        }
                    }
                    return { ...state, target, target_config }
                },
                setTraceWindowSeconds: (state, { windowSeconds }) =>
                    state
                        ? { ...state, target_config: { ...state.target_config, window_seconds: windowSeconds } }
                        : null,
                setHogSource: (state, { source }) =>
                    state && state.evaluation_type === 'hog'
                        ? { ...state, evaluation_config: { ...state.evaluation_config, source } }
                        : state,
                loadEvaluationSuccess: (_, { evaluation }) => evaluation,
                saveEvaluationSuccess: (_, { evaluation }) => evaluation,
            },
        ],
        hogTestResults: {
            clearHogTestResults: () => null,
            setHogSource: () => null,
        },
        selectedModel: [
            '' as string,
            {
                selectModelFromPicker: (_, { modelId }) => modelId,
                setModelConfiguration: (_, { modelConfiguration }) => modelConfiguration?.model || '',
                loadEvaluationSuccess: (_, { evaluation }) => evaluation?.model_configuration?.model || '',
            },
        ],
        selectedPickerProviderKeyId: [
            null as string | null,
            {
                selectModelFromPicker: (_, { providerKeyId }) => providerKeyId,
                setModelConfiguration: (_, { modelConfiguration }) => modelConfiguration?.provider_key_id || null,
                loadEvaluationSuccess: (_, { evaluation }) => evaluation?.model_configuration?.provider_key_id || null,
            },
        ],
        isForceRefresh: [
            false,
            {
                refreshEvaluationRuns: () => true,
                loadEvaluationRunsSuccess: () => false,
                loadEvaluationRunsFailure: () => false,
            },
        ],
        evaluationLoading: [
            false,
            {
                loadEvaluation: () => true,
                loadEvaluationSuccess: () => false,
            },
        ],
        evaluationFormSubmitting: [
            false,
            {
                saveEvaluation: () => true,
                saveEvaluationSuccess: () => false,
                saveEvaluationFailure: () => false,
            },
        ],
        signalEmissionOptimistic: [
            null as boolean | null,
            {
                setSignalEmission: (_, { enabled }) => enabled,
                loadSourceConfigsSuccess: () => null,
                toggleSignalSourceFailure: () => null,
            },
        ],
        hasUnsavedChanges: [
            false,
            {
                setEvaluationName: () => true,
                setEvaluationDescription: () => true,
                setEvaluationPrompt: () => true,
                setEvaluationEnabled: () => true,
                setAllowsNA: () => true,
                setTriggerConditions: () => true,
                setModelConfiguration: () => true,
                setEvaluationType: () => true,
                setEvaluationTarget: () => true,
                setTraceWindowSeconds: () => true,
                setHogSource: () => true,
                saveEvaluationSuccess: () => false,
                loadEvaluationSuccess: () => false,
                resetEvaluation: () => false,
            },
        ],
        evaluationSummaryFilter: [
            'all' as EvaluationSummaryFilter,
            {
                setEvaluationSummaryFilter: (_, { filter }) => filter,
                loadEvaluationSuccess: (_, { evaluation }) =>
                    evaluation?.evaluation_type === 'sentiment' ? DEFAULT_SENTIMENT_RUNS_FILTER : 'all',
            },
        ],
        // Clear summary when filter changes so stale summary doesn't mismatch current filter
        evaluationSummary: {
            setEvaluationSummaryFilter: () => null,
        },
        evaluationSummaryError: [
            false,
            {
                generateEvaluationSummary: () => false,
                generateEvaluationSummarySuccess: () => false,
                generateEvaluationSummaryFailure: () => true,
                setEvaluationSummaryFilter: () => false,
            },
        ],
        summaryExpanded: [
            true,
            {
                toggleSummaryExpanded: (state) => !state,
                generateEvaluationSummarySuccess: () => true,
            },
        ],
        activeTab: [
            'configuration' as string,
            {
                setActiveTab: (_, { tab }) => tab,
                // Show runs tab for existing evaluations, configuration for new
                loadEvaluationSuccess: (_, { evaluation }) => (evaluation?.id ? 'runs' : 'configuration'),
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        loadEvaluationConfigSuccess: () => {
            // The new-eval draft's enabled default is read before the team's evaluation config has
            // loaded — correct it once we know the draft can't actually resolve a model.
            if (
                props.evaluationId === 'new' &&
                values.evaluation?.enabled &&
                !evaluationCanResolveModel(values.evaluation, values.requiresProviderKey, values.isTrialGrandfathered)
            ) {
                actions.setEvaluationEnabled(false)
            }
        },

        loadEvaluation: async () => {
            if (props.evaluationId && props.evaluationId !== 'new') {
                try {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return
                    }

                    // nosemgrep: prefer-codegen-api
                    const evaluation = await api.get(`/api/environments/${teamId}/evaluations/${props.evaluationId}/`)
                    actions.loadEvaluationSuccess(evaluation)
                } catch (error) {
                    console.error('Failed to load evaluation:', error)
                    actions.loadEvaluationSuccess(null)
                }
            } else if (props.evaluationId === 'new') {
                // Initialize new evaluation
                // Check if we should pre-fill from a template
                const template = props.templateKey
                    ? defaultEvaluationTemplates.find((t) => t.key === props.templateKey)
                    : undefined

                const baseFields = {
                    id: '',
                    name: template?.name || '',
                    description: template?.description || '',
                    // Starting a keyless draft enabled would 400 on save for teams that require a key.
                    enabled: !values.requiresProviderKey,
                    status: 'active' as const,
                    status_reason: null,
                    status_reason_detail: null,
                    output_type: 'boolean' as const,
                    output_config: {},
                    conditions: [
                        {
                            id: `cond-${Date.now()}`,
                            rollout_percentage: DEFAULT_CONDITION_ROLLOUT_PERCENTAGE,
                            properties: [],
                        },
                    ],
                    target: 'generation' as const,
                    target_config: {},
                    model_configuration: null,
                    total_runs: 0,
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                }
                const newEvaluation: EvaluationConfig =
                    props.evaluationType === 'sentiment'
                        ? {
                              ...baseFields,
                              evaluation_type: 'sentiment' as const,
                              evaluation_config: { source: DEFAULT_SENTIMENT_SOURCE },
                              output_type: 'sentiment' as const,
                              output_config: {},
                          }
                        : template?.evaluation_type === 'hog'
                          ? {
                                ...baseFields,
                                evaluation_type: 'hog' as const,
                                evaluation_config: { source: template.source, bytecode: [] },
                            }
                          : {
                                ...baseFields,
                                evaluation_type: 'llm_judge' as const,
                                evaluation_config: {
                                    prompt: template && 'prompt' in template ? template.prompt : '',
                                },
                            }
                actions.loadEvaluationSuccess(newEvaluation)
            }
        },

        refreshEvaluationRuns: () => {
            actions.loadEvaluationRuns()
        },

        regenerateEvaluationSummary: () => {
            posthog.capture('llma evaluation regenerate clicked', {
                filter: values.evaluationSummaryFilter,
                runs_to_summarize: values.runsToSummarizeCount,
            })
            actions.generateEvaluationSummary({ forceRefresh: true })
        },

        trackSummarizeClicked: () => {
            posthog.capture('llma evaluation summarize clicked', {
                filter: values.evaluationSummaryFilter,
                runs_to_summarize: values.runsToSummarizeCount,
            })
        },

        setEvaluationSummaryFilter: ({ filter, previousFilter }) => {
            posthog.capture('llma evaluation summary filter changed', {
                filter,
                previous_filter: previousFilter,
            })
        },

        toggleSummaryExpanded: () => {
            posthog.capture('llma evaluation summary toggled', {
                expanded: values.summaryExpanded,
                filter: values.evaluationSummaryFilter,
            })
        },

        resetEvaluation: () => {
            // Reset any pending report-config draft alongside the evaluation so
            // Cancel/Back clears both forms (the report draft lives in a separate
            // keyed logic — see evaluationReportLogic).
            const reportLogicKey = props.evaluationId === 'new' ? 'new' : props.evaluationId
            const reportLogic = evaluationReportLogic({ evaluationId: reportLogicKey })
            if (reportLogic.isMounted()) {
                if (reportLogic.values.activeReport) {
                    reportLogic.actions.seedDraftFromReport(reportLogic.values.activeReport)
                } else {
                    reportLogic.actions.resetDraft()
                }
            }
            if (props.evaluationId === 'new') {
                const newEvaluation: EvaluationConfig = {
                    id: '',
                    name: '',
                    description: '',
                    enabled: !values.requiresProviderKey,
                    status: 'active',
                    status_reason: null,
                    status_reason_detail: null,
                    evaluation_type: 'llm_judge',
                    evaluation_config: {
                        prompt: '',
                    },
                    output_type: 'boolean',
                    output_config: {},
                    conditions: [
                        {
                            id: `cond-${Date.now()}`,
                            rollout_percentage: DEFAULT_CONDITION_ROLLOUT_PERCENTAGE,
                            properties: [],
                        },
                    ],
                    target: 'generation',
                    target_config: {},
                    model_configuration: null,
                    total_runs: 0,
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                }
                actions.loadEvaluationSuccess(newEvaluation)
            } else {
                actions.loadEvaluationSuccess(values.originalEvaluation)
            }
        },

        setSignalEmission: ({ enabled }) => {
            const configs: SignalSourceConfig[] = values.sourceConfigs ?? []
            const existing = configs.find(
                (c) =>
                    c.source_product === SignalSourceProduct.LlmAnalytics &&
                    c.source_type === SignalSourceType.Evaluation
            )

            const currentIds: string[] = existing?.config?.evaluation_ids ?? []
            const newIds = enabled
                ? [...new Set([...currentIds, props.evaluationId])]
                : currentIds.filter((id: string) => id !== props.evaluationId)

            actions.toggleSignalSource({
                sourceProduct: SignalSourceProduct.LlmAnalytics,
                sourceType: SignalSourceType.Evaluation,
                enabled: true,
                config: { ...existing?.config, evaluation_ids: newIds },
            })
        },

        saveEvaluation: async () => {
            try {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }

                const isNew = props.evaluationId === 'new'
                const response = isNew
                    ? // nosemgrep: prefer-codegen-api
                      await api.create(`/api/environments/${teamId}/evaluations/`, values.evaluation!)
                    : // nosemgrep: prefer-codegen-api
                      await api.update(
                          `/api/environments/${teamId}/evaluations/${props.evaluationId}/`,
                          values.evaluation!
                      )
                actions.saveEvaluationSuccess(response)

                // Piggyback the scheduled-report draft onto the main save so the single
                // "Save changes" button at the top of the page commits both forms. The
                // evaluationReportLogic is only mounted when EvaluationReportConfig is
                // rendered (gated on the reports feature flag), so skip when it isn't —
                // reading .values on an unmounted keyed logic would throw.
                const reportLogicKey = isNew ? 'new' : props.evaluationId
                const reportLogic = evaluationReportLogic({ evaluationId: reportLogicKey })
                if (response?.id && evaluationSupportsReports(response) && reportLogic.isMounted()) {
                    try {
                        await persistReportDraft(
                            teamId,
                            response.id,
                            reportLogic.values.configDraft,
                            reportLogic.values.activeReport
                        )
                    } catch (reportError) {
                        // Don't block navigation if the (optional) report save fails —
                        // the eval itself already saved successfully.
                        posthog.captureException(reportError, { tag: 'eval-report-persist-on-eval-save' })
                        lemonToast.error('Evaluation saved, but scheduled report changes could not be saved.')
                    }
                }

                router.actions.push(urls.aiObservabilityEvaluations(), router.values.searchParams)
            } catch (error) {
                const message = evaluationErrorMessage(error, 'Failed to save evaluation')
                lemonToast.error(message)
                actions.saveEvaluationFailure(message)
            }
        },

        selectModelFromPicker: ({ modelId, providerKeyId }) => {
            if (!modelId) {
                return
            }
            const trialProvider = parseTrialProviderKeyId(providerKeyId)
            if (trialProvider) {
                actions.setModelConfiguration({
                    provider: trialProvider,
                    model: modelId,
                    provider_key_id: null,
                })
                return
            }
            const key = values.providerKeys.find((k: LLMProviderKey) => k.id === providerKeyId)
            if (key) {
                actions.setModelConfiguration({
                    provider: key.provider,
                    model: modelId,
                    provider_key_id: providerKeyId,
                })
            }
        },
        setEvaluationType: ({ evaluationType }) => {
            if (!evaluationTypeDefaultsToBooleanOutput(evaluationType) && values.activeTab === 'reports') {
                actions.setActiveTab('configuration')
            }
        },
    })),

    selectors({
        isNewEvaluation: [(_, props) => [props.evaluationId], (evaluationId: string) => evaluationId === 'new'],

        signalEmissionEnabled: [
            (s, props) => [s.signalEmissionOptimistic, s.sourceConfigs, props.evaluationId],
            (optimistic: boolean | null, sourceConfigs: SignalSourceConfig[] | null, evaluationId: string): boolean => {
                if (optimistic !== null) {
                    return optimistic
                }
                if (!sourceConfigs) {
                    return false
                }
                const llmEvalConfig = sourceConfigs.find(
                    (c) =>
                        c.source_product === SignalSourceProduct.LlmAnalytics &&
                        c.source_type === SignalSourceType.Evaluation
                )
                const ids: string[] = llmEvalConfig?.config?.evaluation_ids ?? []
                return !!llmEvalConfig?.enabled && ids.includes(evaluationId)
            },
        ],

        formValid: [
            (s) => [s.evaluation],
            (evaluation) => {
                if (!evaluation) {
                    return false
                }
                const hasValidName = evaluation.name.length > 0
                const hasValidConditions =
                    evaluation.conditions.length > 0 &&
                    evaluation.conditions.every(
                        (c) => (c.rollout_percentage ?? 0) > 0 && (c.rollout_percentage ?? 0) <= 100
                    )

                let hasValidConfig = false
                if (evaluation.evaluation_type === 'hog') {
                    hasValidConfig = evaluation.evaluation_config.source.trim().length > 0
                } else if (evaluation.evaluation_type === 'sentiment') {
                    hasValidConfig = true
                } else if (isLLMJudgeEvaluation(evaluation)) {
                    hasValidConfig = evaluation.evaluation_config.prompt.length > 0
                }

                return hasValidName && hasValidConfig && hasValidConditions
            },
        ],

        canEnable: [
            (s) => [s.evaluation, s.requiresProviderKey, s.isTrialGrandfathered],
            (
                evaluation: EvaluationConfig | null,
                requiresProviderKey: boolean,
                isTrialGrandfathered: boolean
            ): boolean => {
                if (!evaluation) {
                    return true
                }
                return evaluationCanResolveModel(evaluation, requiresProviderKey, isTrialGrandfathered)
            },
        ],

        canEnableReason: [
            (s) => [s.canEnable],
            (canEnable: boolean): string | null => {
                if (canEnable) {
                    return null
                }
                return 'Add a provider API key to enable this evaluation.'
            },
        ],

        evaluationProviderKeyIssue: [
            (s) => [s.evaluation, s.providerKeys],
            (evaluation: EvaluationConfig | null, providerKeys: LLMProviderKey[]): LLMProviderKey | null => {
                return getUnhealthyProviderKey(providerKeys, evaluation?.model_configuration?.provider_key_id)
            },
        ],

        runsLookup: [
            (s) => [s.evaluationRuns],
            (runs): Record<string, EvaluationRun> => {
                const lookup: Record<string, EvaluationRun> = {}
                for (const run of runs) {
                    if (run.generation_id) {
                        lookup[run.generation_id] = run
                    }
                }
                return lookup
            },
        ],

        runsSummary: [
            (s) => [s.evaluationRuns],
            (runs) => {
                if (runs.length === 0) {
                    return null
                }

                const successfulRuns = runs.filter((r) => r.result === true).length
                const failedRuns = runs.filter((r) => r.result === false).length
                const errorRuns = runs.filter((r) => r.status === 'failed').length
                // Applicable runs excludes N/A (result === null)
                const applicableRuns = successfulRuns + failedRuns
                const completedRuns = runs.filter((r) => r.status === 'completed').length

                return {
                    total: runs.length,
                    successful: successfulRuns,
                    failed: failedRuns,
                    errors: errorRuns,
                    successRate: applicableRuns > 0 ? Math.round((successfulRuns / applicableRuns) * 100) : 0,
                    applicabilityRate: completedRuns > 0 ? Math.round((applicableRuns / completedRuns) * 100) : 0,
                }
            },
        ],

        filteredEvaluationRuns: [
            (s) => [s.evaluationRuns, s.evaluationSummaryFilter],
            (runs: EvaluationRun[], filter: EvaluationSummaryFilter): EvaluationRun[] =>
                filterEvaluationRuns(runs, filter),
        ],

        runsToSummarizeCount: [
            (s) => [s.filteredEvaluationRuns, s.evaluationSummaryFilter],
            (filteredRuns: EvaluationRun[], filter: EvaluationSummaryFilter): number => {
                // When 'all', filteredEvaluationRuns includes non-completed runs, but summarization only uses completed
                const count =
                    filter === 'all' ? filteredRuns.filter((r) => r.status === 'completed').length : filteredRuns.length
                return Math.min(count, EVALUATION_SUMMARY_MAX_RUNS)
            },
        ],

        breadcrumbs: [
            (s) => [s.evaluation, router.selectors.searchParams],
            (evaluation: EvaluationConfig | null, searchParams: Record<string, any>): Breadcrumb[] => [
                {
                    name: 'Evaluations',
                    path: combineUrl(urls.aiObservabilityEvaluations(), searchParams).url,
                    key: 'AIObservabilityEvaluations',
                    iconType: 'llm_evaluations',
                },
                {
                    name: evaluation?.name || 'New Evaluation',
                    key: 'AIObservabilityEvaluationEdit',
                    iconType: 'llm_evaluations',
                },
            ],
        ],

        maxContext: [
            (s) => [s.evaluation],
            (evaluation: EvaluationConfig | null): MaxContextInput[] => {
                if (!evaluation) {
                    return []
                }
                return [
                    createMaxContextHelpers.evaluation({
                        id: evaluation.id || 'new',
                        name: evaluation.name,
                        description: evaluation.description,
                        evaluation_type: evaluation.evaluation_type,
                        hog_source: evaluation.evaluation_type === 'hog' ? evaluation.evaluation_config.source : null,
                    }),
                ]
            },
        ],
    }),

    urlToAction(({ actions, props }) => ({
        '/ai-evals/evaluations/:id': ({ id }, _, __, { method }) => {
            // Only reload when navigating to a different evaluation, not on search param changes (e.g., pagination)
            const newEvaluationId = id && id !== 'new' ? id : 'new'
            if (method === 'PUSH' && newEvaluationId !== props.evaluationId) {
                actions.loadEvaluation()
                if (props.evaluationId !== 'new') {
                    actions.loadEvaluationRuns()
                }
            }
        },
    })),

    afterMount(({ actions, props }) => {
        actions.loadProviderKeys()
        actions.loadSourceConfigs()
        actions.loadEvaluation()
        if (props.evaluationId !== 'new') {
            actions.loadEvaluationRuns()
        }
    }),
])
