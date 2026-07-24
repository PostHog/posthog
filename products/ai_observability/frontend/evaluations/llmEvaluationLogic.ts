import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { MaxContextInput, createMaxContextHelpers } from '~/scenes/max/maxTypes'
import { Breadcrumb } from '~/types'

import {
    evaluationsCreate,
    evaluationsPartialUpdate,
    evaluationsRetrieve,
    evaluationsTestHogCreate,
    llmAnalyticsEvaluationSummaryCreate,
} from '../generated/api'
import type { TestHogRequestApi, TestHogResultItemApi } from '../generated/api.schemas'
import { parsePlaygroundProviderKeyId } from '../ModelPicker'
import { LLMProviderKey, llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import type { EvaluationConfig as TeamEvaluationConfig } from '../settings/llmProviderKeysLogic'
import { getUnhealthyProviderKey } from '../settings/providerKeyStateUtils'
import { EvaluationRunsStats, queryEvaluationRuns, queryEvaluationRunsStats } from '../utils'
import { evaluationErrorMessage } from './apiErrors'
import { EVALUATION_SUMMARY_MAX_RUNS } from './constants'
import {
    evaluationCanResolveModel,
    evaluationSupportsReports,
    evaluationSupportsRunSummary,
    isBooleanEvaluationOutput,
    isLLMJudgeEvaluation,
} from './evaluationCapabilities'
import { EvaluationBackTarget, getEvaluationBackTarget } from './evaluationNavigation'
import { evaluationReportLogic, persistReportDraft } from './evaluationReportLogic'
import { getHogEvalExample } from './hogEvalExamples'
import { EvaluationTemplateKey, defaultEvaluationTemplates } from './templates'
import type {
    EvaluationConditionSet,
    EvaluationConfig,
    EvaluationRun,
    EvaluationSettleStrategy,
    EvaluationSummary,
    EvaluationSummaryFilter,
    EvaluationTarget,
    EvaluationTargetConfig,
    EvaluationType,
    HogEvaluation,
    LLMJudgeEvaluation,
    ModelConfiguration,
    SentimentEvaluation,
} from './types'

// Mirror the backend defaults in evaluation_configs.py — pre-filled when a strategy is
// selected. The backend re-defaults and clamps regardless.
export const DEFAULT_TRACE_WINDOW_SECONDS = 30 * 60
export const DEFAULT_TRACE_QUIET_PERIOD_SECONDS = 5 * 60
export const DEFAULT_TRACE_MAX_AGE_SECONDS = 2 * 60 * 60

export const DEFAULT_HOG_SOURCE = getHogEvalExample('output_not_empty').source

const LEGACY_HOG_DEFAULT_SOURCES = [
    `// Check that the output is not empty
let result := length(output) > 0
if (not result) {
    print('Output is empty')
}
return result`,
    `// Check that the trace produced at least one event
let result := length(events) > 0
if (not result) {
    print('Trace has no events')
}
return result`,
]

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
        evaluation_config: { source: DEFAULT_HOG_SOURCE },
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

function buildHogTestRequest(evaluation: HogEvaluation): TestHogRequestApi {
    const request: TestHogRequestApi = {
        source: evaluation.evaluation_config.source,
        sample_count: 5,
        allows_na: evaluation.output_config?.allows_na ?? false,
        conditions: evaluation.conditions
            .filter((condition) => condition.properties && condition.properties.length > 0)
            .map((condition) => ({ properties: condition.properties })),
        target: evaluation.target,
    }
    if (evaluation.target === 'trace') {
        request.target_config = {
            window_seconds: evaluation.target_config.window_seconds ?? DEFAULT_TRACE_WINDOW_SECONDS,
        }
    }
    return request
}

export interface LLMEvaluationLogicProps {
    evaluationId: string
    templateKey?: EvaluationTemplateKey
    evaluationType?: EvaluationType
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface llmEvaluationLogicValues {
    activeProviderKey: LLMProviderKey | null | undefined // llmProviderKeysLogic
    providerKeys: LLMProviderKey[] // llmProviderKeysLogic
    providerKeysLoading: boolean // llmProviderKeysLogic
    requiresProviderKey: boolean // llmProviderKeysLogic
    activeTab: string
    breadcrumbs: Breadcrumb[]
    canEnable: boolean
    canEnableReason: string | null
    evaluation: EvaluationConfig | null
    evaluationBackTarget: EvaluationBackTarget
    evaluationFormSubmitting: boolean
    evaluationLoading: boolean
    evaluationProviderKeyIssue: LLMProviderKey | null
    evaluationRuns: EvaluationRun[]
    evaluationRunsLoading: boolean
    evaluationSummary: EvaluationSummary | null
    evaluationSummaryError: boolean
    evaluationSummaryFilter: EvaluationSummaryFilter
    evaluationSummaryLoading: boolean
    filteredEvaluationRuns: EvaluationRun[]
    formValid: boolean
    hasUnsavedChanges: boolean
    hogTestResults: TestHogResultItemApi[] | null
    hogTestResultsLoading: boolean
    isForceRefresh: boolean
    isNewEvaluation: boolean
    maxContext: MaxContextInput[]
    modelSelectionRequired: boolean
    originalEvaluation: EvaluationConfig | null
    runsLookup: Record<string, EvaluationRun>
    runsStats: EvaluationRunsStats | null
    runsStatsLoading: boolean
    runsSummary: {
        applicabilityRate: number
        errors: number
        failed: number
        successful: number
        successRate: number
        total: number
    } | null
    runsToSummarizeCount: number
    selectedModel: string
    selectedPickerProviderKeyId: string | null
    summaryExpanded: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface llmEvaluationLogicActions {
    loadEvaluationConfigSuccess: (
        evaluationConfig: TeamEvaluationConfig | null,
        payload?: any
    ) => {
        evaluationConfig: TeamEvaluationConfig | null
        payload?: any
    } // llmProviderKeysLogic
    loadProviderKeys: () => any // llmProviderKeysLogic
    clearHogTestResults: () => {
        value: true
    }
    generateEvaluationSummary: ({ forceRefresh }: { forceRefresh?: boolean }) => {
        forceRefresh?: boolean
    }
    generateEvaluationSummaryFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    generateEvaluationSummarySuccess: (
        evaluationSummary: EvaluationSummary | null,
        payload?: {
            forceRefresh?: boolean
        }
    ) => {
        evaluationSummary: EvaluationSummary | null
        payload?: {
            forceRefresh?: boolean
        }
    }
    loadEvaluation: () => {
        value: true
    }
    loadEvaluationRuns: () => any
    loadEvaluationRunsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadEvaluationRunsSuccess: (
        evaluationRuns: EvaluationRun[],
        payload?: any
    ) => {
        evaluationRuns: EvaluationRun[]
        payload?: any
    }
    loadEvaluationSuccess: (evaluation: EvaluationConfig | null) => {
        evaluation: EvaluationConfig | null
    }
    loadRunsStats: () => any
    loadRunsStatsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadRunsStatsSuccess: (
        runsStats: EvaluationRunsStats | null,
        payload?: any
    ) => {
        runsStats: EvaluationRunsStats | null
        payload?: any
    }
    patchTargetConfig: (patch: Partial<Omit<EvaluationTargetConfig, 'strategy'>>) => {
        patch: Partial<Omit<EvaluationTargetConfig, 'strategy'>>
    }
    refreshEvaluationRuns: () => {
        value: true
    }
    regenerateEvaluationSummary: () => {
        value: true
    }
    resetEvaluation: () => {
        value: true
    }
    saveEvaluation: () => {
        value: true
    }
    saveEvaluationFailure: (error: string) => {
        error: string
    }
    saveEvaluationSuccess: (evaluation: EvaluationConfig) => {
        evaluation: EvaluationConfig
    }
    selectModelFromPicker: (
        modelId: string,
        providerKeyId: string
    ) => {
        modelId: string
        providerKeyId: string
    }
    setActiveTab: (tab: string) => {
        tab: string
    }
    setAllowsNA: (allowsNA: boolean) => {
        allowsNA: boolean
    }
    setEvaluationDescription: (description: string) => {
        description: string
    }
    setEvaluationEnabled: (enabled: boolean) => {
        enabled: boolean
    }
    setEvaluationName: (name: string) => {
        name: string
    }
    setEvaluationPrompt: (prompt: string) => {
        prompt: string
    }
    setEvaluationSummaryFilter: (
        filter: EvaluationSummaryFilter,
        previousFilter: EvaluationSummaryFilter
    ) => {
        filter: EvaluationSummaryFilter
        previousFilter: EvaluationSummaryFilter
    }
    setEvaluationTarget: (target: EvaluationTarget) => {
        target: EvaluationTarget
    }
    setEvaluationType: (evaluationType: EvaluationType) => {
        evaluationType: EvaluationType
    }
    setHogSource: (source: string) => {
        source: string
    }
    setModelConfiguration: (modelConfiguration: ModelConfiguration | null) => {
        modelConfiguration: ModelConfiguration | null
    }
    setSettleStrategy: (strategy: EvaluationSettleStrategy) => {
        strategy: EvaluationSettleStrategy
    }
    setTriggerConditions: (conditions: EvaluationConditionSet[]) => {
        conditions: EvaluationConditionSet[]
    }
    testHogOnSample: (_?: void) => void
    testHogOnSampleFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    testHogOnSampleSuccess: (
        hogTestResults: TestHogResultItemApi[] | null,
        payload?: void
    ) => {
        hogTestResults: TestHogResultItemApi[] | null
        payload?: void
    }
    toggleSummaryExpanded: () => {
        value: true
    }
    trackSummarizeClicked: () => {
        value: true
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface llmEvaluationLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        isNewEvaluation: (evaluationId: string) => boolean
        evaluationBackTarget: (isNewEvaluation: boolean, searchParams: Record<string, any>) => EvaluationBackTarget
        modelSelectionRequired: (
            evaluation: EvaluationConfig | null,
            originalEvaluation: EvaluationConfig | null,
            evaluationId: string
        ) => boolean
        formValid: (evaluation: EvaluationConfig | null, modelSelectionRequired: boolean) => boolean
        canEnable: (
            evaluation: EvaluationConfig | null,
            activeProviderKey: LLMProviderKey | null | undefined
        ) => boolean
        canEnableReason: (canEnable: boolean) => string | null
        evaluationProviderKeyIssue: (
            evaluation: EvaluationConfig | null,
            providerKeys: LLMProviderKey[]
        ) => LLMProviderKey | null
        runsLookup: (evaluationRuns: EvaluationRun[]) => Record<string, EvaluationRun>
        runsSummary: (runsStats: EvaluationRunsStats | null) => {
            applicabilityRate: number
            errors: number
            failed: number
            successful: number
            successRate: number
            total: number
        } | null
        filteredEvaluationRuns: (
            evaluationRuns: EvaluationRun[],
            evaluationSummaryFilter: EvaluationSummaryFilter
        ) => EvaluationRun[]
        runsToSummarizeCount: (
            filteredEvaluationRuns: EvaluationRun[],
            evaluationSummaryFilter: EvaluationSummaryFilter
        ) => number
        breadcrumbs: (
            evaluation: EvaluationConfig | null,
            isNewEvaluation: boolean,
            evaluationBackTarget: EvaluationBackTarget,
            searchParams: Record<string, any>
        ) => Breadcrumb[]
        maxContext: (evaluation: EvaluationConfig | null) => MaxContextInput[]
    }
}

export type llmEvaluationLogicType = MakeLogicType<
    llmEvaluationLogicValues,
    llmEvaluationLogicActions,
    LLMEvaluationLogicProps,
    llmEvaluationLogicMeta
>

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
            ['providerKeys', 'providerKeysLoading', 'requiresProviderKey', 'activeProviderKey'],
        ],
        actions: [llmProviderKeysLogic, ['loadProviderKeys', 'loadEvaluationConfigSuccess']],
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
        setSettleStrategy: (strategy: EvaluationSettleStrategy) => ({ strategy }),
        // Duration fields only — switching strategy must go through setSettleStrategy so the
        // bag is fully reseeded (the strategies carry disjoint fields).
        patchTargetConfig: (patch: Partial<Omit<EvaluationTargetConfig, 'strategy'>>) => ({ patch }),
        setHogSource: (source: string) => ({ source }),

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
            null as TestHogResultItemApi[] | null,
            {
                testHogOnSample: async (_?: void, breakpoint?: () => void): Promise<TestHogResultItemApi[] | null> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    const evaluation = values.evaluation
                    if (!evaluation || evaluation.evaluation_type !== 'hog') {
                        return null
                    }

                    const request = buildHogTestRequest(evaluation)
                    const requestFingerprint = JSON.stringify(request)
                    let results: TestHogResultItemApi[]
                    try {
                        const response = await evaluationsTestHogCreate(teamId.toString(), request)
                        results = response.results.map((result) => ({
                            ...result,
                            reasoning: result.reasoning ?? '',
                        }))
                    } catch (e: unknown) {
                        const message = e instanceof Error ? e.message : typeof e === 'string' ? e : 'Unknown error'
                        results = [
                            {
                                sample_id: 'error',
                                sample_type: evaluation.target,
                                event_uuid: null,
                                trace_id: null,
                                input_preview: '',
                                output_preview: '',
                                result: null,
                                reasoning: '',
                                error: typeof message === 'string' ? message : JSON.stringify(message),
                            },
                        ]
                    }

                    breakpoint?.()
                    const currentEvaluation = values.evaluation
                    if (
                        !currentEvaluation ||
                        currentEvaluation.evaluation_type !== 'hog' ||
                        JSON.stringify(buildHogTestRequest(currentEvaluation)) !== requestFingerprint
                    ) {
                        return null
                    }
                    return results
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
        runsStats: [
            null as EvaluationRunsStats | null,
            {
                loadRunsStats: async () => {
                    if (!props.evaluationId || props.evaluationId === 'new') {
                        return null
                    }

                    return await queryEvaluationRunsStats({
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
                    if (!evaluationSupportsRunSummary(values.evaluation)) {
                        return null
                    }

                    const requestFilter = values.evaluationSummaryFilter
                    if (
                        requestFilter !== 'all' &&
                        requestFilter !== 'pass' &&
                        requestFilter !== 'fail' &&
                        requestFilter !== 'na'
                    ) {
                        return null
                    }

                    // Backend fetches data server-side by ID - we just pass the filter
                    const response = await llmAnalyticsEvaluationSummaryCreate(teamId.toString(), {
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
                    // Seed a fixed-window settle config when switching to trace so the fields show a
                    // sane default; clear the bag when switching back so we don't persist stale settings.
                    const target_config: EvaluationTargetConfig =
                        target === 'trace'
                            ? { strategy: 'fixed_window', window_seconds: DEFAULT_TRACE_WINDOW_SECONDS }
                            : {}
                    if (
                        state.evaluation_type === 'hog' &&
                        LEGACY_HOG_DEFAULT_SOURCES.includes(state.evaluation_config.source)
                    ) {
                        return {
                            ...state,
                            target,
                            target_config,
                            evaluation_config: { ...state.evaluation_config, source: DEFAULT_HOG_SOURCE },
                        }
                    }
                    return { ...state, target, target_config }
                },
                setSettleStrategy: (state, { strategy }) => {
                    if (!state || state.target !== 'trace') {
                        return state
                    }
                    // Full reseed rather than a patch: the two strategies carry disjoint fields and
                    // extra="forbid" on the backend rejects leftovers from the other one.
                    const target_config: EvaluationTargetConfig =
                        strategy === 'inactivity'
                            ? {
                                  strategy: 'inactivity',
                                  quiet_period_seconds: DEFAULT_TRACE_QUIET_PERIOD_SECONDS,
                                  max_age_seconds: DEFAULT_TRACE_MAX_AGE_SECONDS,
                              }
                            : { strategy: 'fixed_window', window_seconds: DEFAULT_TRACE_WINDOW_SECONDS }
                    return { ...state, target_config }
                },
                patchTargetConfig: (state, { patch }) =>
                    state ? { ...state, target_config: { ...state.target_config, ...patch } } : null,
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
            setAllowsNA: () => null,
            setEvaluationTarget: () => null,
            setEvaluationType: () => null,
            setHogSource: () => null,
            setTraceWindowSeconds: () => null,
            setTriggerConditions: () => null,
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
                setSettleStrategy: () => true,
                patchTargetConfig: () => true,
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
                !evaluationCanResolveModel(values.evaluation, values.activeProviderKey)
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

                    const evaluation = await evaluationsRetrieve(teamId.toString(), props.evaluationId)
                    actions.loadEvaluationSuccess(evaluation as unknown as EvaluationConfig)
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
                    props.evaluationType === 'sentiment' || template?.evaluation_type === 'sentiment'
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

        loadEvaluationRuns: () => {
            actions.loadRunsStats()
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

        saveEvaluation: async () => {
            try {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }

                if (!values.formValid || !values.evaluation) {
                    const message =
                        values.evaluation?.evaluation_type === 'llm_judge' &&
                        !values.evaluation.model_configuration?.model.trim()
                            ? 'Select a judge model before saving.'
                            : 'Some required fields are missing. Please review the configuration.'
                    lemonToast.error(message)
                    actions.saveEvaluationFailure(message)
                    return
                }

                const isNew = props.evaluationId === 'new'
                const reportLogicKey = isNew ? 'new' : props.evaluationId
                const reportLogic = evaluationReportLogic({ evaluationId: reportLogicKey })
                if (
                    evaluationSupportsReports(values.evaluation) &&
                    reportLogic.isMounted() &&
                    reportLogic.values.configError
                ) {
                    lemonToast.error(reportLogic.values.configError)
                    actions.saveEvaluationFailure(reportLogic.values.configError)
                    return
                }

                const response = (isNew
                    ? await evaluationsCreate(
                          teamId.toString(),
                          values.evaluation as Parameters<typeof evaluationsCreate>[1]
                      )
                    : await evaluationsPartialUpdate(
                          teamId.toString(),
                          props.evaluationId,
                          values.evaluation as Parameters<typeof evaluationsPartialUpdate>[2]
                      )) as unknown as EvaluationConfig
                actions.saveEvaluationSuccess(response)

                // Piggyback the scheduled-report draft onto the main save so the single
                // "Save changes" button at the top of the page commits both forms. The
                // evaluationReportLogic is only mounted when EvaluationReportConfig is
                // rendered (gated on the reports feature flag), so skip when it isn't —
                // reading .values on an unmounted keyed logic would throw.
                if (response?.id && evaluationSupportsReports(response) && reportLogic.isMounted()) {
                    const reportConfigStillLoading =
                        !isNew && reportLogic.values.reportsLoading && !reportLogic.values.activeReport
                    if (reportConfigStillLoading) {
                        router.actions.push(getEvaluationBackTarget(false, router.values.searchParams).path)
                        return
                    }

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

                router.actions.push(getEvaluationBackTarget(false, router.values.searchParams).path)
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
            const playgroundProvider = parsePlaygroundProviderKeyId(providerKeyId)
            if (playgroundProvider) {
                actions.setModelConfiguration({
                    provider: playgroundProvider,
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
        setEvaluationType: () => {
            if (!evaluationSupportsReports(values.evaluation) && values.activeTab === 'reports') {
                actions.setActiveTab('configuration')
            }
        },
    })),

    selectors({
        isNewEvaluation: [(_, props) => [props.evaluationId], (evaluationId: string) => evaluationId === 'new'],

        evaluationBackTarget: [
            (s) => [s.isNewEvaluation, router.selectors.searchParams],
            (isNewEvaluation: boolean, searchParams: Record<string, any>): EvaluationBackTarget =>
                getEvaluationBackTarget(isNewEvaluation, searchParams),
        ],

        modelSelectionRequired: [
            (s, props) => [s.evaluation, s.originalEvaluation, props.evaluationId],
            (
                evaluation: EvaluationConfig | null,
                originalEvaluation: EvaluationConfig | null,
                evaluationId: string
            ): boolean => {
                if (!isLLMJudgeEvaluation(evaluation)) {
                    return false
                }
                if (evaluationId === 'new' || originalEvaluation?.evaluation_type !== 'llm_judge') {
                    return true
                }
                return originalEvaluation.model_configuration != null
            },
        ],

        formValid: [
            (s) => [s.evaluation, s.modelSelectionRequired],
            (evaluation: EvaluationConfig | null, modelSelectionRequired: boolean) => {
                if (!evaluation) {
                    return false
                }
                const hasValidName = (evaluation.name?.length ?? 0) > 0
                const hasValidConditions =
                    (evaluation.conditions?.length ?? 0) > 0 &&
                    (evaluation.conditions ?? []).every(
                        (c) => (c.rollout_percentage ?? 0) > 0 && (c.rollout_percentage ?? 0) <= 100
                    )

                let hasValidConfig = false
                if (evaluation.evaluation_type === 'hog') {
                    hasValidConfig = (evaluation.evaluation_config?.source?.trim().length ?? 0) > 0
                } else if (evaluation.evaluation_type === 'sentiment') {
                    hasValidConfig = true
                } else if (isLLMJudgeEvaluation(evaluation)) {
                    hasValidConfig =
                        (evaluation.evaluation_config?.prompt?.length ?? 0) > 0 &&
                        (!modelSelectionRequired || (evaluation.model_configuration?.model.trim().length ?? 0) > 0)
                }

                return hasValidName && hasValidConfig && hasValidConditions
            },
        ],

        canEnable: [
            (s) => [s.evaluation, s.activeProviderKey],
            (evaluation: EvaluationConfig | null, activeProviderKey: LLMProviderKey | null | undefined): boolean => {
                if (!evaluation) {
                    return true
                }
                return evaluationCanResolveModel(evaluation, activeProviderKey)
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
            (runs: EvaluationRun[]): Record<string, EvaluationRun> => {
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
            (s) => [s.runsStats],
            (stats: EvaluationRunsStats | null) => {
                if (!stats || stats.total === 0) {
                    return null
                }

                const { total, applicable, passed } = stats
                // Applicable runs excludes N/A results
                const failed = applicable - passed

                return {
                    total,
                    successful: passed,
                    failed,
                    errors: 0,
                    successRate: applicable > 0 ? Math.round((passed / applicable) * 100) : 0,
                    applicabilityRate: total > 0 ? Math.round((applicable / total) * 100) : 0,
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
            (s) => [s.evaluation, s.isNewEvaluation, s.evaluationBackTarget, router.selectors.searchParams],
            (
                evaluation: EvaluationConfig | null,
                isNewEvaluation: boolean,
                evaluationBackTarget: EvaluationBackTarget,
                searchParams: Record<string, any>
            ): Breadcrumb[] => {
                const evaluationsTarget = getEvaluationBackTarget(false, searchParams)
                const parentBreadcrumbs: Breadcrumb[] =
                    isNewEvaluation && evaluationBackTarget.name !== 'Evaluations'
                        ? [
                              ...(evaluationBackTarget.name === 'Templates' ? [evaluationsTarget] : []),
                              evaluationBackTarget,
                          ]
                        : [evaluationsTarget]

                return [
                    ...parentBreadcrumbs,
                    {
                        name: evaluation?.name || 'New Evaluation',
                        key: 'AIObservabilityEvaluationEdit',
                        iconType: 'llm_evaluations',
                    },
                ]
            },
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
        actions.loadEvaluation()
        if (props.evaluationId !== 'new') {
            actions.loadEvaluationRuns()
        }
    }),
])
