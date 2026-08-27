import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { MaxContextInput, createMaxContextHelpers } from '~/scenes/max/maxTypes'
import { ActivityScope, Breadcrumb } from '~/types'

import {
    evaluationsCreate,
    evaluationsPartialUpdate,
    evaluationsRetrieve,
    evaluationsTestHogCreate,
} from '../generated/api'
import type { TestHogRequestApi, TestHogResultItemApi } from '../generated/api.schemas'
import { parsePlaygroundProviderKeyId } from '../ModelPicker'
import { LLMProviderKey, llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import type { EvaluationConfig as TeamEvaluationConfig } from '../settings/llmProviderKeysLogic'
import { getUnhealthyProviderKey } from '../settings/providerKeyStateUtils'
import { EvaluationRunsStats, queryEvaluationRuns, queryEvaluationRunsStats } from '../utils'
import { evaluationErrorMessage } from './apiErrors'
import {
    evaluationCanResolveModel,
    evaluationSupportsReports,
    isBooleanEvaluationOutput,
    isLLMJudgeEvaluation,
} from './evaluationCapabilities'
import { EvaluationBackTarget, getEvaluationBackTarget } from './evaluationNavigation'
import { evaluationReportLogic, persistReportDraft } from './evaluationReportLogic'
import { getHogEvalExample } from './hogEvalExamples'
import { llmEvaluationsLogic } from './llmEvaluationsLogic'
import { EvaluationTemplateKey, defaultEvaluationTemplates } from './templates'
import type {
    EvaluationConditionSet,
    EvaluationConfig,
    EvaluationRun,
    EvaluationRunsFilter,
    EvaluationSettleStrategy,
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

export const DEFAULT_SESSION_WINDOW_SECONDS = 30 * 60
export const DEFAULT_SESSION_QUIET_PERIOD_SECONDS = 60 * 60
export const DEFAULT_SESSION_MAX_AGE_SECONDS = 24 * 60 * 60

const AGGREGATE_TARGETS: EvaluationTarget[] = ['trace', 'session']
const EVALUATION_DETAIL_TABS = new Set(['configuration', 'reports', 'runs'])

function evaluationDetailTab(value: unknown): string | null {
    return typeof value === 'string' && EVALUATION_DETAIL_TABS.has(value) ? value : null
}

function seedSettleConfig(target: EvaluationTarget, strategy: EvaluationSettleStrategy): EvaluationTargetConfig {
    if (!AGGREGATE_TARGETS.includes(target)) {
        return {}
    }
    const isSession = target === 'session'
    if (strategy === 'inactivity') {
        return {
            strategy: 'inactivity',
            quiet_period_seconds: isSession ? DEFAULT_SESSION_QUIET_PERIOD_SECONDS : DEFAULT_TRACE_QUIET_PERIOD_SECONDS,
            max_age_seconds: isSession ? DEFAULT_SESSION_MAX_AGE_SECONDS : DEFAULT_TRACE_MAX_AGE_SECONDS,
        }
    }
    return {
        strategy: 'fixed_window',
        window_seconds: isSession ? DEFAULT_SESSION_WINDOW_SECONDS : DEFAULT_TRACE_WINDOW_SECONDS,
    }
}

// A fixed window measured from the first matching generation is unrelated to when a session ends,
// so sessions open on inactivity. Traces keep fixed_window to match every stored config.
function defaultStrategyForTarget(target: EvaluationTarget): EvaluationSettleStrategy {
    return target === 'session' ? 'inactivity' : 'fixed_window'
}

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

function filterEvaluationRuns(runs: EvaluationRun[], filter: EvaluationRunsFilter): EvaluationRun[] {
    if (filter === 'all') {
        return runs
    }

    const completedRuns = runs.filter((r) => r.status === 'completed')
    // A skipped run carries result=false when the evaluation disallows N/A, so it has to be
    // excluded before the outcome is read or it lands in the fail bucket without being graded.
    const gradedRuns = completedRuns.filter((r) => !r.skipped)
    if (filter === 'pass') {
        return gradedRuns.filter((r) => r.result === true)
    }
    if (filter === 'fail') {
        return gradedRuns.filter((r) => r.result === false)
    }
    if (filter === 'na') {
        return gradedRuns.filter((r) => r.result === null)
    }

    return completedRuns.filter((r) => r.sentiment_label?.toLowerCase() === filter)
}

type TestableHogEvaluation = HogEvaluation

function isTestableHogEvaluation(evaluation: EvaluationConfig | null): evaluation is TestableHogEvaluation {
    return evaluation?.evaluation_type === 'hog'
}

function buildHogTestRequest(evaluation: TestableHogEvaluation): TestHogRequestApi {
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
    if (evaluation.target === 'session') {
        // Preview against the settle duration this evaluation is actually configured with, so the
        // sample only contains sessions it would already have graded. A fixed_window session
        // settles a fixed time after its first matching generation; sampling on that same duration
        // of inactivity is the conservative read of it — every session in the sample has certainly
        // settled, though a still-active one that settled mid-conversation won't be sampled.
        request.target_config = {
            quiet_period_seconds:
                evaluation.target_config.strategy === 'fixed_window'
                    ? (evaluation.target_config.window_seconds ?? DEFAULT_SESSION_WINDOW_SECONDS)
                    : (evaluation.target_config.quiet_period_seconds ?? DEFAULT_SESSION_QUIET_PERIOD_SECONDS),
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
    evaluationRunsError: boolean
    evaluationRunsFilter: EvaluationRunsFilter
    evaluationRunsLoading: boolean
    filteredEvaluationRuns: EvaluationRun[]
    formValid: boolean
    hasUnsavedChanges: boolean
    hogTestMessage: string | null
    hogTestResults: TestHogResultItemApi[] | null
    hogTestResultsLoading: boolean
    isForceRefresh: boolean
    isNewEvaluation: boolean
    maxContext: MaxContextInput[]
    modelSelectionRequired: boolean
    originalEvaluation: EvaluationConfig | null
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
    selectedModel: string
    selectedPickerProviderKeyId: string | null
    sidePanelContext: SidePanelSceneContext | null
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
        requestedTab: string | null
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
    setEvaluationRunsFilter: (
        filter: EvaluationRunsFilter,
        previousFilter: EvaluationRunsFilter
    ) => {
        filter: EvaluationRunsFilter
        previousFilter: EvaluationRunsFilter
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
    setHogTestMessage: (message: string | null) => {
        message: string | null
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
            evaluationRunsFilter: EvaluationRunsFilter
        ) => EvaluationRun[]
        breadcrumbs: (
            evaluation: EvaluationConfig | null,
            isNewEvaluation: boolean,
            evaluationBackTarget: EvaluationBackTarget,
            searchParams: Record<string, any>
        ) => Breadcrumb[]
        maxContext: (evaluation: EvaluationConfig | null) => MaxContextInput[]
        sidePanelContext: (
            evaluation: EvaluationConfig | null,
            isNewEvaluation: boolean
        ) => SidePanelSceneContext | null
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
        loadEvaluationSuccess: (evaluation: EvaluationConfig | null) => ({
            evaluation,
            requestedTab: evaluationDetailTab(router.values.searchParams.evaluation_tab),
        }),
        resetEvaluation: true,

        // Evaluation runs actions
        refreshEvaluationRuns: true,

        // Model selection actions
        selectModelFromPicker: (modelId: string, providerKeyId: string) => ({ modelId, providerKeyId }),

        // Hog test actions
        clearHogTestResults: true,
        setHogTestMessage: (message: string | null) => ({ message }),

        // Runs table actions
        setEvaluationRunsFilter: (filter: EvaluationRunsFilter, previousFilter: EvaluationRunsFilter) => ({
            filter,
            previousFilter,
        }),
    }),

    loaders(({ props, values, actions }) => ({
        hogTestResults: [
            null as TestHogResultItemApi[] | null,
            {
                testHogOnSample: async (_?: void, breakpoint?: () => void): Promise<TestHogResultItemApi[] | null> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    const evaluation = values.evaluation
                    if (!isTestableHogEvaluation(evaluation)) {
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
                        // An empty sample is a real answer, not a failure. Without the API's
                        // explanation the panel is just an empty table, which reads as broken.
                        actions.setHogTestMessage(results.length === 0 ? (response.message ?? null) : null)
                    } catch (e: unknown) {
                        actions.setHogTestMessage(null)
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
                        !isTestableHogEvaluation(currentEvaluation) ||
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
                    // Seed the target's default settle config so the fields show sane values;
                    // clear the bag for generation so we don't persist stale settings.
                    const target_config = seedSettleConfig(target, defaultStrategyForTarget(target))
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
                    if (!state || !AGGREGATE_TARGETS.includes(state.target)) {
                        return state
                    }
                    // Full reseed rather than a patch: the two strategies carry disjoint fields and
                    // extra="forbid" on the backend rejects leftovers from the other one.
                    return { ...state, target_config: seedSettleConfig(state.target, strategy) }
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
            setSettleStrategy: () => null,
            patchTargetConfig: () => null,
            setTriggerConditions: () => null,
        },
        hogTestMessage: [
            null as string | null,
            {
                setHogTestMessage: (_, { message }) => message,
                clearHogTestResults: () => null,
                testHogOnSample: () => null,
            },
        ],
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
        // The runs loader keeps its default empty list when the query fails. Track the failure so
        // the table can show a real error state with retry instead of the "no runs yet" empty state.
        evaluationRunsError: [
            false as boolean,
            {
                loadEvaluationRuns: () => false,
                loadEvaluationRunsSuccess: () => false,
                loadEvaluationRunsFailure: () => true,
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
        evaluationRunsFilter: [
            'all' as EvaluationRunsFilter,
            {
                setEvaluationRunsFilter: (_, { filter }) => filter,
                loadEvaluationSuccess: (_, { evaluation }) =>
                    evaluation?.evaluation_type === 'sentiment' ? DEFAULT_SENTIMENT_RUNS_FILTER : 'all',
            },
        ],
        activeTab: [
            'configuration' as string,
            {
                setActiveTab: (_, { tab }) => tab,
                // Show runs tab for existing evaluations, configuration for new
                loadEvaluationSuccess: (_, { evaluation, requestedTab }) =>
                    requestedTab ?? (evaluation?.id ? 'runs' : 'configuration'),
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
                    directory_id:
                        typeof router.values.searchParams.directory === 'string'
                            ? router.values.searchParams.directory
                            : null,
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

        setEvaluationRunsFilter: ({ filter, previousFilter }) => {
            // pinned: analytics event name - renaming it breaks existing dashboards
            posthog.capture('llma evaluation summary filter changed', {
                filter,
                previous_filter: previousFilter,
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
                    directory_id:
                        typeof router.values.searchParams.directory === 'string'
                            ? router.values.searchParams.directory
                            : null,
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
                // The list and the self-driving table read from llmEvaluationsLogic, which only
                // fetches on mount. Refresh it here so they show the eval we just saved.
                llmEvaluationsLogic.findMounted()?.actions.loadEvaluations()
                if (isNew) {
                    globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.SetUpLlmEvaluation)
                }

                // Piggyback the scheduled-report draft onto the main save so the single
                // "Save changes" button at the top of the page commits both forms. Only
                // the components that render the report config or history mount
                // evaluationReportLogic, so skip when none of them is on screen —
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
            (s) => [s.evaluationRuns, s.evaluationRunsFilter],
            (runs: EvaluationRun[], filter: EvaluationRunsFilter): EvaluationRun[] =>
                filterEvaluationRuns(runs, filter),
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

        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.evaluation, s.isNewEvaluation],
            (evaluation: EvaluationConfig | null, isNewEvaluation: boolean): SidePanelSceneContext | null =>
                evaluation?.id && !isNewEvaluation
                    ? {
                          activity_scope: ActivityScope.EVALUATION,
                          activity_item_id: evaluation.id,
                          access_control_resource: 'evaluation',
                          access_control_resource_id: evaluation.id,
                      }
                    : null,
        ],
    }),

    urlToAction(({ actions, props, values }) => ({
        [urls.aiObservabilityEvaluation(':id')]: ({ id }, searchParams, __, { method }) => {
            const requestedTab =
                evaluationDetailTab(searchParams.evaluation_tab) ?? (id === 'new' ? 'configuration' : 'runs')
            if (requestedTab !== values.activeTab) {
                actions.setActiveTab(requestedTab)
            }

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

    actionToUrl(({ props }) => ({
        setActiveTab: ({ tab }) => {
            const defaultTab = props.evaluationId === 'new' ? 'configuration' : 'runs'
            const evaluationTab = tab === defaultTab ? undefined : tab
            if (router.values.searchParams.evaluation_tab === evaluationTab) {
                return
            }

            return [
                router.values.location.pathname,
                { ...router.values.searchParams, evaluation_tab: evaluationTab },
                router.values.hashParams,
                { replace: true },
            ]
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
