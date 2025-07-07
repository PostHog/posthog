import { actions, connect, isBreakpoint, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { hasFormErrors, toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { addProjectIdIfMissing } from 'lib/utils/router-utils'
import { billingLogic } from 'scenes/billing/billingLogic'
import {
    indexToVariantKeyFeatureFlagPayloads,
    featureFlagLogic as sceneFeatureFlagLogic,
    validateFeatureFlagKey,
    variantKeyToIndexFeatureFlagPayloads,
} from 'scenes/feature-flags/featureFlagLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { projectLogic } from 'scenes/projectLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { urls } from 'scenes/urls'

import { activationLogic, ActivationTask } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { performQuery, QUERY_TIMEOUT_ERROR_MESSAGE } from '~/queries/query'
import {
    AnyEntityNode,
    CachedExperimentFunnelsQueryResponse,
    CachedExperimentQueryResponse,
    CachedExperimentTrendsQueryResponse,
    CachedLegacyExperimentQueryResponse,
    CachedNewExperimentQueryResponse,
    ExperimentExposureCriteria,
    ExperimentExposureQueryResponse,
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentMetricType,
    ExperimentTrendsQuery,
    FunnelsQuery,
    InsightVizNode,
    NodeKind,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import {
    Breadcrumb,
    BreakdownAttributionType,
    BreakdownType,
    CohortType,
    CountPerActorMathType,
    DashboardType,
    Experiment,
    ExperimentStatsMethod,
    FeatureFlagType,
    FunnelExperimentVariant,
    InsightType,
    MultivariateFlagVariant,
    ProductKey,
    ProjectTreeRef,
    PropertyMathType,
    TrendExperimentVariant,
} from '~/types'
import {
    EXPERIMENT_MAX_PRIMARY_METRICS,
    EXPERIMENT_MAX_SECONDARY_METRICS,
    EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS,
    MetricInsightId,
} from './constants'
import {
    conversionRateForVariant,
    expectedRunningTime,
    getSignificanceDetails,
    minimumSampleSizePerVariant,
    recommendedExposureForCountData,
} from './experimentCalculations'
import type { experimentLogicType } from './experimentLogicType'
import { experimentsLogic } from './experimentsLogic'
import { holdoutsLogic } from './holdoutsLogic'
import { addExposureToMetric, compose, getInsight, getQuery } from './metricQueryUtils'
import { getDefaultMetricTitle } from './MetricsView/shared/utils'
import { modalsLogic } from './modalsLogic'
import { SharedMetric } from './SharedMetrics/sharedMetricLogic'
import { sharedMetricsLogic } from './SharedMetrics/sharedMetricsLogic'
import {
    featureFlagEligibleForExperiment,
    isLegacyExperiment,
    percentageDistribution,
    transformFiltersForWinningVariant,
} from './utils'

const NEW_EXPERIMENT: Experiment = {
    id: 'new',
    name: '',
    type: 'product',
    feature_flag_key: '',
    filters: {},
    metrics: [],
    metrics_secondary: [],
    saved_metrics_ids: [],
    saved_metrics: [],
    parameters: {
        feature_flag_variants: [
            { key: 'control', rollout_percentage: 50 },
            { key: 'test', rollout_percentage: 50 },
        ],
    },
    secondary_metrics: [],
    created_at: null,
    created_by: null,
    updated_at: null,
    holdout_id: null,
    exposure_criteria: {
        filterTestAccounts: true,
    },
}

export const DEFAULT_MDE = 30

export const FORM_MODES = {
    create: 'create',
    duplicate: 'duplicate',
    update: 'update',
} as const

/**
 * get the values of formModes as a union type
 * we don't really need formModes unless we need to do FORM_MODES[num]
 * this could be just an union type
 */
export type FormModes = (typeof FORM_MODES)[keyof typeof FORM_MODES]

export interface ExperimentLogicProps {
    experimentId?: Experiment['id']
    formMode?: FormModes
}

interface MetricLoadingConfig {
    metrics: any[]
    experimentId: Experiment['id']
    refresh?: boolean
    onSetLegacyResults: (
        results: (
            | CachedLegacyExperimentQueryResponse
            | CachedExperimentTrendsQueryResponse
            | CachedExperimentFunnelsQueryResponse
            | null
        )[]
    ) => void
    onSetResults: (results: CachedNewExperimentQueryResponse[]) => void
    onSetErrors: (errors: any[]) => void
    onTimeout: (experimentId: Experiment['id'], metric: any) => void
}

const loadMetrics = async ({
    metrics,
    experimentId,
    refresh,
    onSetLegacyResults,
    onSetResults,
    onSetErrors,
    onTimeout,
}: MetricLoadingConfig): Promise<void[]> => {
    const legacyResults: (
        | CachedLegacyExperimentQueryResponse
        | CachedExperimentTrendsQueryResponse
        | CachedExperimentFunnelsQueryResponse
        | null
    )[] = []

    const results: CachedNewExperimentQueryResponse[] = []
    const currentErrors = new Array(metrics.length).fill(null)

    return await Promise.all(
        metrics.map(async (metric, index) => {
            try {
                let queryWithExperimentId
                if (metric.kind === NodeKind.ExperimentMetric) {
                    queryWithExperimentId = {
                        kind: NodeKind.ExperimentQuery,
                        metric: metric,
                        experiment_id: experimentId,
                    }
                } else {
                    queryWithExperimentId = {
                        ...metric,
                        experiment_id: experimentId,
                    }
                }
                const response = await performQuery(
                    setLatestVersionsOnQuery(queryWithExperimentId),
                    undefined,
                    refresh ? 'force_async' : 'async'
                )

                // Convert ExperimentQuery responses to typed responses
                if (
                    metric.kind === NodeKind.ExperimentMetric ||
                    queryWithExperimentId.kind === NodeKind.ExperimentQuery
                ) {
                    const typedResponse = convertToTypedExperimentResponse(response as CachedExperimentQueryResponse)
                    if (typedResponse) {
                        if (isLegacyExperimentResponse(typedResponse)) {
                            legacyResults[index] = {
                                ...typedResponse,
                                fakeInsightId: Math.random().toString(36).substring(2, 15),
                            } as CachedLegacyExperimentQueryResponse & { fakeInsightId: string }
                        } else if (isNewExperimentResponse(typedResponse)) {
                            results[index] = typedResponse
                        }
                    }
                } else {
                    // For trends/funnels queries, keep original response
                    legacyResults[index] = {
                        ...response,
                        fakeInsightId: Math.random().toString(36).substring(2, 15),
                    } as (CachedExperimentTrendsQueryResponse | CachedExperimentFunnelsQueryResponse) & {
                        fakeInsightId: string
                    }
                }
                onSetLegacyResults([...legacyResults])
                onSetResults([...results])
            } catch (error: any) {
                const errorDetailMatch = error.detail?.match(/\{.*\}/)
                const errorDetail = errorDetailMatch ? JSON.parse(errorDetailMatch[0]) : error.detail || error.message

                currentErrors[index] = {
                    detail: errorDetail,
                    statusCode: error.status,
                    hasDiagnostics: !!errorDetailMatch,
                }
                onSetErrors(currentErrors)

                if (errorDetail === QUERY_TIMEOUT_ERROR_MESSAGE) {
                    onTimeout(experimentId, metric)
                }

                legacyResults[index] = null
                onSetLegacyResults([...legacyResults])
                onSetResults([...results])
            }
        })
    )
}

// Type guards to distinguish between legacy and new experiment responses
export function isLegacyExperimentResponse(
    response: CachedExperimentQueryResponse
): response is CachedLegacyExperimentQueryResponse {
    return 'variants' in response && response.variants !== null
}

export function isNewExperimentResponse(
    response: CachedExperimentQueryResponse
): response is CachedNewExperimentQueryResponse {
    return 'baseline' in response && response.baseline !== null
}

// Union type for strongly typed experiment responses
export type TypedExperimentResponse = CachedLegacyExperimentQueryResponse | CachedNewExperimentQueryResponse

// Utility function to convert generic response to typed response
function convertToTypedExperimentResponse(response: CachedExperimentQueryResponse): TypedExperimentResponse | null {
    if (isLegacyExperimentResponse(response)) {
        return response
    }

    if (isNewExperimentResponse(response)) {
        return response
    }

    // If response doesn't match either pattern, return null
    return null
}

export const experimentLogic = kea<experimentLogicType>([
    props({} as ExperimentLogicProps),
    key((props) => props.experimentId || 'new'),
    path((key) => ['scenes', 'experiment', 'experimentLogic', key]),
    connect(() => ({
        values: [
            projectLogic,
            ['currentProjectId'],
            groupsModel,
            ['aggregationLabel', 'groupTypes', 'showGroupsOptions'],
            sceneLogic,
            ['activeScene'],
            featureFlagLogic,
            ['featureFlags'],
            holdoutsLogic,
            ['holdouts'],
            billingLogic,
            ['billing'],
            // Hook the insight state to get the results for the sample size estimation
            funnelDataLogic({ dashboardItemId: MetricInsightId.Funnels }),
            ['results as funnelResults', 'conversionMetrics'],
            trendsDataLogic({ dashboardItemId: MetricInsightId.Trends }),
            ['results as trendResults'],
            // Hook into the loading state of the metric insight
            insightDataLogic({ dashboardItemId: MetricInsightId.Trends }),
            ['insightDataLoading as trendMetricInsightLoading'],
            insightDataLogic({ dashboardItemId: MetricInsightId.Funnels }),
            ['insightDataLoading as funnelMetricInsightLoading'],
            sharedMetricsLogic,
            ['sharedMetrics'],
        ],
        actions: [
            experimentsLogic,
            ['updateExperiments', 'addToExperiments'],
            eventUsageLogic,
            [
                'reportExperimentCreated',
                'reportExperimentViewed',
                'reportExperimentLaunched',
                'reportExperimentCompleted',
                'reportExperimentArchived',
                'reportExperimentReset',
                'reportExperimentExposureCohortCreated',
                'reportExperimentVariantShipped',
                'reportExperimentVariantScreenshotUploaded',
                'reportExperimentResultsLoadingTimeout',
                'reportExperimentReleaseConditionsViewed',
                'reportExperimentHoldoutAssigned',
                'reportExperimentSharedMetricAssigned',
                'reportExperimentDashboardCreated',
                'reportExperimentMetricTimeout',
            ],
            teamLogic,
            ['addProductIntent'],
            featureFlagsLogic,
            ['updateFlag'],
            modalsLogic,
            [
                'openPrimaryMetricModal',
                'closePrimaryMetricModal',
                'openSecondaryMetricModal',
                'closeSecondaryMetricModal',
                'openPrimarySharedMetricModal',
                'openSecondarySharedMetricModal',
                'closeStopExperimentModal',
                'closeShipVariantModal',
                'openReleaseConditionsModal',
            ],
        ],
    })),
    actions({
        setExperimentMissing: true,
        setExperiment: (experiment: Partial<Experiment>) => ({ experiment }),
        createExperiment: (draft?: boolean, folder?: string | null) => ({ draft, folder }),
        setExperimentType: (type?: string) => ({ type }),
        addVariant: true,
        removeVariant: (idx: number) => ({ idx }),
        setEditExperiment: (editing: boolean) => ({ editing }),
        setExposureAndSampleSize: (exposure: number, sampleSize: number) => ({ exposure, sampleSize }),
        refreshExperimentResults: (forceRefresh?: boolean) => ({ forceRefresh }),
        updateExperimentMetrics: true,
        updateExperimentCollectionGoal: true,
        updateExposureCriteria: true,
        changeExperimentStartDate: (startDate: string) => ({ startDate }),
        changeExperimentEndDate: (endDate: string) => ({ endDate }),
        launchExperiment: true,
        endExperiment: true,
        archiveExperiment: true,
        resetRunningExperiment: true,
        updateExperimentVariantImages: (variantPreviewMediaIds: Record<string, string[]>) => ({
            variantPreviewMediaIds,
        }),
        setExposureCriteria: (exposureCriteria: ExperimentExposureCriteria) => ({ exposureCriteria }),
        setTabKey: (tabKey: string) => ({ tabKey }),
        createExperimentDashboard: true,
        setIsCreatingExperimentDashboard: (isCreating: boolean) => ({ isCreating }),
        setUnmodifiedExperiment: (experiment: Experiment) => ({ experiment }),
        restoreUnmodifiedExperiment: true,
        setValidExistingFeatureFlag: (featureFlag: FeatureFlagType | null) => ({ featureFlag }),
        setFeatureFlagValidationError: (error: string) => ({ error }),
        validateFeatureFlag: (featureFlagKey: string) => ({ featureFlagKey }),
        // METRICS
        setMetric: ({
            metricIdx,
            name,
            metric,
            isSecondary = false,
        }: {
            metricIdx: number
            name?: string
            metric: ExperimentMetric
            isSecondary?: boolean
        }) => ({ metricIdx, name, metric, isSecondary }),
        setTrendsMetric: ({
            metricIdx,
            name,
            series,
            filterTestAccounts,
            isSecondary = false,
        }: {
            metricIdx: number
            name?: string
            series?: AnyEntityNode[]
            filterTestAccounts?: boolean
            isSecondary?: boolean
        }) => ({ metricIdx, name, series, filterTestAccounts, isSecondary }),
        setTrendsExposureMetric: ({
            metricIdx,
            name,
            series,
            filterTestAccounts,
            isSecondary = false,
        }: {
            metricIdx: number
            name?: string
            series?: AnyEntityNode[]
            filterTestAccounts?: boolean
            isSecondary?: boolean
        }) => ({ metricIdx, name, series, filterTestAccounts, isSecondary }),
        setFunnelsMetric: ({
            metricIdx,
            name,
            series,
            filterTestAccounts,
            breakdownAttributionType,
            breakdownAttributionValue,
            funnelWindowInterval,
            funnelWindowIntervalUnit,
            aggregation_group_type_index,
            funnelAggregateByHogQL,
            isSecondary,
        }: {
            metricIdx: number
            name?: string
            series?: AnyEntityNode[]
            filterTestAccounts?: boolean
            breakdownAttributionType?: BreakdownAttributionType
            breakdownAttributionValue?: number
            funnelWindowInterval?: number
            funnelWindowIntervalUnit?: string
            aggregation_group_type_index?: number
            funnelAggregateByHogQL?: string
            isSecondary?: boolean
        }) => ({
            metricIdx,
            name,
            series,
            filterTestAccounts,
            breakdownAttributionType,
            breakdownAttributionValue,
            funnelWindowInterval,
            funnelWindowIntervalUnit,
            aggregation_group_type_index,
            funnelAggregateByHogQL,
            isSecondary,
        }),
        addSharedMetricsToExperiment: (
            sharedMetricIds: SharedMetric['id'][],
            metadata: { type: 'primary' | 'secondary' }
        ) => ({
            sharedMetricIds,
            metadata,
        }),
        removeSharedMetricFromExperiment: (sharedMetricId: SharedMetric['id']) => ({ sharedMetricId }),
        duplicateMetric: ({ metricIndex, isSecondary }: { metricIndex: number; isSecondary: boolean }) => ({
            metricIndex,
            isSecondary,
        }),
        // METRICS RESULTS
        setLegacyPrimaryMetricsResults: (
            results: (
                | CachedLegacyExperimentQueryResponse
                | CachedExperimentTrendsQueryResponse
                | CachedExperimentFunnelsQueryResponse
                | null
            )[]
        ) => ({ results }),
        setPrimaryMetricsResults: (results: CachedNewExperimentQueryResponse[]) => ({ results }),
        setPrimaryMetricsResultsLoading: (loading: boolean) => ({ loading }),
        loadPrimaryMetricsResults: (refresh?: boolean) => ({ refresh }),
        setPrimaryMetricsResultsErrors: (errors: any[]) => ({ errors }),
        setSecondaryMetricsResults: (results: CachedNewExperimentQueryResponse[]) => ({ results }),
        loadSecondaryMetricsResults: (refresh?: boolean) => ({ refresh }),
        setSecondaryMetricsResultsErrors: (errors: any[]) => ({ errors }),
        setSecondaryMetricsResultsLoading: (loading: boolean) => ({ loading }),
        setLegacySecondaryMetricsResults: (
            results: (
                | CachedLegacyExperimentQueryResponse
                | CachedExperimentTrendsQueryResponse
                | CachedExperimentFunnelsQueryResponse
                | null
            )[]
        ) => ({ results }),
        updateDistribution: (featureFlag: FeatureFlagType) => ({ featureFlag }),
    }),
    reducers({
        experiment: [
            { ...NEW_EXPERIMENT } as Experiment,
            {
                setExperiment: (state, { experiment }) => {
                    return { ...state, ...experiment }
                },
                addVariant: (state) => {
                    if (state?.parameters?.feature_flag_variants) {
                        const newRolloutPercentages = percentageDistribution(
                            state.parameters.feature_flag_variants.length + 1
                        )
                        const updatedRolloutPercentageVariants = state.parameters.feature_flag_variants.map(
                            (variant: MultivariateFlagVariant, i: number) => ({
                                ...variant,
                                rollout_percentage: newRolloutPercentages[i],
                            })
                        )
                        return {
                            ...state,
                            parameters: {
                                ...state.parameters,
                                feature_flag_variants: [
                                    ...updatedRolloutPercentageVariants,
                                    {
                                        key: `test_group_${state.parameters.feature_flag_variants.length}`,
                                        rollout_percentage: newRolloutPercentages[newRolloutPercentages.length - 1],
                                    },
                                ],
                            },
                        }
                    }
                    return state
                },
                removeVariant: (state, { idx }) => {
                    if (!state) {
                        return { ...NEW_EXPERIMENT }
                    }
                    const variants = [...(state.parameters?.feature_flag_variants || [])]
                    variants.splice(idx, 1)
                    const newRolloutPercentages = percentageDistribution(
                        (state?.parameters?.feature_flag_variants || []).length - 1
                    )
                    const updatedVariants = variants.map((variant: MultivariateFlagVariant, i: number) => ({
                        ...variant,
                        rollout_percentage: newRolloutPercentages[i],
                    }))

                    return {
                        ...state,
                        parameters: {
                            ...state.parameters,
                            feature_flag_variants: updatedVariants,
                        },
                    }
                },
                setExposureCriteria: (
                    state,
                    { exposureCriteria }: { exposureCriteria: ExperimentExposureCriteria }
                ) => {
                    return {
                        ...state,
                        exposure_criteria: { ...state.exposure_criteria, ...exposureCriteria },
                    }
                },
                setMetric: (state, { metricIdx, metric, isSecondary }) => {
                    const metricsKey = isSecondary ? 'metrics_secondary' : 'metrics'
                    const metrics = [...(state?.[metricsKey] || [])]

                    metrics[metricIdx] = metric

                    return {
                        ...state,
                        [metricsKey]: metrics,
                    }
                },
                setTrendsMetric: (state, { metricIdx, name, series, filterTestAccounts, isSecondary }) => {
                    const metricsKey = isSecondary ? 'metrics_secondary' : 'metrics'
                    const metrics = [...(state?.[metricsKey] || [])]
                    const metric = metrics[metricIdx]

                    metrics[metricIdx] = {
                        ...metric,
                        ...(name !== undefined && { name }),
                        count_query: {
                            ...(metric as ExperimentTrendsQuery).count_query,
                            ...(series && { series }),
                            ...(filterTestAccounts !== undefined && { filterTestAccounts }),
                        },
                    } as ExperimentTrendsQuery

                    return {
                        ...state,
                        [metricsKey]: metrics,
                    }
                },
                setTrendsExposureMetric: (state, { metricIdx, name, series, filterTestAccounts, isSecondary }) => {
                    const metricsKey = isSecondary ? 'metrics_secondary' : 'metrics'
                    const metrics = [...(state?.[metricsKey] || [])]
                    const metric = metrics[metricIdx]

                    metrics[metricIdx] = {
                        ...metric,
                        ...(name !== undefined && { name }),
                        exposure_query: {
                            ...(metric as ExperimentTrendsQuery).exposure_query,
                            ...(series && { series }),
                            ...(filterTestAccounts !== undefined && { filterTestAccounts }),
                        },
                    } as ExperimentTrendsQuery

                    return {
                        ...state,
                        [metricsKey]: metrics,
                    }
                },
                setFunnelsMetric: (
                    state,
                    {
                        metricIdx,
                        name,
                        series,
                        filterTestAccounts,
                        breakdownAttributionType,
                        breakdownAttributionValue,
                        funnelWindowInterval,
                        funnelWindowIntervalUnit,
                        aggregation_group_type_index,
                        funnelAggregateByHogQL,
                        isSecondary,
                    }
                ) => {
                    const metricsKey = isSecondary ? 'metrics_secondary' : 'metrics'
                    const metrics = [...(state?.[metricsKey] || [])]
                    const metric = metrics[metricIdx]

                    metrics[metricIdx] = {
                        ...metric,
                        ...(name !== undefined && { name }),
                        funnels_query: {
                            ...(metric as ExperimentFunnelsQuery).funnels_query,
                            ...(series && { series }),
                            ...(filterTestAccounts !== undefined && { filterTestAccounts }),
                            ...(aggregation_group_type_index !== undefined && { aggregation_group_type_index }),
                            funnelsFilter: {
                                ...(metric as ExperimentFunnelsQuery).funnels_query.funnelsFilter,
                                ...(breakdownAttributionType && { breakdownAttributionType }),
                                ...(breakdownAttributionValue !== undefined && { breakdownAttributionValue }),
                                ...(funnelWindowInterval !== undefined && { funnelWindowInterval }),
                                ...(funnelWindowIntervalUnit && { funnelWindowIntervalUnit }),
                                ...(funnelAggregateByHogQL !== undefined && { funnelAggregateByHogQL }),
                            },
                        },
                    } as ExperimentFunnelsQuery

                    return {
                        ...state,
                        [metricsKey]: metrics,
                    }
                },
                duplicateMetric: (state, { metricIndex, isSecondary }) => {
                    const metricsKey = isSecondary ? 'metrics_secondary' : 'metrics'
                    const metrics = [...(state?.[metricsKey] || [])]

                    const originalMetric = metrics[metricIndex]

                    if (!originalMetric) {
                        return state
                    }

                    // Check if duplicating would exceed the 10 metric limit
                    const currentMetricCount = metrics.length
                    const sharedMetricsCount =
                        state?.saved_metrics?.filter(
                            (savedMetric) => savedMetric.metadata.type === (isSecondary ? 'secondary' : 'primary')
                        ).length || 0
                    const totalMetricCount = currentMetricCount + sharedMetricsCount

                    if (
                        totalMetricCount >=
                        (!isSecondary ? EXPERIMENT_MAX_PRIMARY_METRICS : EXPERIMENT_MAX_SECONDARY_METRICS)
                    ) {
                        // Return state unchanged if limit would be exceeded
                        return state
                    }

                    const name = originalMetric.name
                        ? `${originalMetric.name} (copy)`
                        : originalMetric.kind === NodeKind.ExperimentMetric
                        ? `${getDefaultMetricTitle(originalMetric)} (copy)`
                        : undefined

                    const newMetric = { ...originalMetric, id: undefined, name }
                    metrics.splice(metricIndex + 1, 0, newMetric)

                    return {
                        ...state,
                        [metricsKey]: metrics,
                    }
                },
            },
        ],
        experimentMissing: [
            false,
            {
                setExperimentMissing: () => true,
            },
        ],
        unmodifiedExperiment: [
            null as Experiment | null,
            {
                setUnmodifiedExperiment: (_, { experiment }) => experiment,
            },
        ],
        tabKey: [
            'results',
            {
                setTabKey: (_, { tabKey }) => tabKey,
            },
        ],
        // PRIMARY METRICS
        legacyPrimaryMetricsResults: [
            [] as (
                | CachedLegacyExperimentQueryResponse
                | CachedExperimentTrendsQueryResponse
                | CachedExperimentFunnelsQueryResponse
                | null
            )[],
            {
                setLegacyPrimaryMetricsResults: (_, { results }) => results,
            },
        ],
        primaryMetricsResults: [
            [] as CachedNewExperimentQueryResponse[],
            {
                setPrimaryMetricsResults: (_, { results }) => results,
                loadPrimaryMetricsResults: () => [],
                loadExperiment: () => [],
            },
        ],
        primaryMetricsResultsLoading: [
            false,
            {
                setPrimaryMetricsResultsLoading: (_, { loading }) => loading,
            },
        ],
        primaryMetricsResultsErrors: [
            [] as any[],
            {
                setPrimaryMetricsResultsErrors: (_, { errors }) => errors,
                loadPrimaryMetricsResults: () => [],
                loadExperiment: () => [],
            },
        ],
        // SECONDARY METRICS
        legacySecondaryMetricsResults: [
            [] as (
                | CachedLegacyExperimentQueryResponse
                | CachedExperimentTrendsQueryResponse
                | CachedExperimentFunnelsQueryResponse
                | null
            )[],
            {
                setLegacySecondaryMetricsResults: (_, { results }) => results,
            },
        ],
        secondaryMetricsResults: [
            [] as CachedNewExperimentQueryResponse[],
            {
                setSecondaryMetricsResults: (_, { results }) => results,
                loadSecondaryMetricsResults: () => [],
                loadExperiment: () => [],
            },
        ],
        secondaryMetricsResultsLoading: [
            false,
            {
                setSecondaryMetricsResultsLoading: (_, { loading }) => loading,
            },
        ],
        secondaryMetricsResultsErrors: [
            [] as any[],
            {
                setSecondaryMetricsResultsErrors: (_, { errors }) => errors,
                loadSecondaryMetricsResults: () => [],
                loadExperiment: () => [],
            },
        ],
        editingPrimaryMetricIndex: [
            null as number | null,
            {
                openPrimaryMetricModal: (_, { index }) => index,
                closePrimaryMetricModal: () => null,
                updateExperimentMetrics: () => null,
                setEditingPrimaryMetricIndex: (_, { index }) => index,
            },
        ],
        editingSecondaryMetricIndex: [
            null as number | null,
            {
                openSecondaryMetricModal: (_, { index }) => index,
                closeSecondaryMetricModal: () => null,
                updateExperimentMetrics: () => null,
            },
        ],
        editingSharedMetricId: [
            null as SharedMetric['id'] | null,
            {
                openPrimarySharedMetricModal: (_, { sharedMetricId }) => sharedMetricId,
                openSecondarySharedMetricModal: (_, { sharedMetricId }) => sharedMetricId,
                updateExperimentMetrics: () => null,
            },
        ],
        isCreatingExperimentDashboard: [
            false,
            {
                setIsCreatingExperimentDashboard: (_, { isCreating }) => isCreating,
            },
        ],
        validExistingFeatureFlag: [
            null as FeatureFlagType | null,
            {
                setValidExistingFeatureFlag: (_, { featureFlag }) => featureFlag,
            },
        ],
        featureFlagValidationError: [
            null as string | null,
            {
                setFeatureFlagValidationError: (_, { error }) => error,
            },
        ],
    }),
    listeners(({ values, actions, props }) => ({
        createExperiment: async ({ draft, folder }) => {
            const { recommendedRunningTime, recommendedSampleSize, minimumDetectableEffect } = values

            actions.touchExperimentField('name')
            actions.touchExperimentField('feature_flag_key')
            values.experiment.parameters.feature_flag_variants.forEach((_, i) =>
                actions.touchExperimentField(`parameters.feature_flag_variants.${i}.key`)
            )

            if (hasFormErrors(values.experimentErrors)) {
                return
            }

            // Minimum Detectable Effect is calculated based on a loaded insight
            // Terminate if the insight did not manage to load in time
            if (!minimumDetectableEffect) {
                eventUsageLogic.actions.reportExperimentInsightLoadFailed()
                return lemonToast.error(
                    'Failed to load insight. Experiment cannot be saved without this value. Try changing the experiment goal.'
                )
            }

            let response: Experiment | null = null
            const isUpdate = props.formMode === 'update'
            try {
                if (isUpdate) {
                    response = await api.update(
                        `api/projects/${values.currentProjectId}/experiments/${values.experimentId}`,
                        {
                            ...values.experiment,
                            parameters: {
                                ...values.experiment?.parameters,
                                recommended_running_time: recommendedRunningTime,
                                recommended_sample_size: recommendedSampleSize,
                                minimum_detectable_effect: minimumDetectableEffect,
                            },
                            ...(!draft && { start_date: dayjs() }),
                            // backwards compatibility: Remove any global properties set on the experiment.
                            // These were used to change feature flag targeting, but this is controlled directly
                            // on the feature flag now.
                            filters: {
                                events: [],
                                actions: [],
                                ...values.experiment.filters,
                                properties: [],
                            },
                        }
                    )

                    if (response?.id) {
                        actions.updateExperiments(response)
                        actions.setEditExperiment(false)
                        actions.loadExperimentSuccess(response)
                        return
                    }
                } else {
                    // Check if the new Bayesian stats method feature flag is enabled
                    const useNewBayesianStatsMethod = values.featureFlags[FEATURE_FLAGS.NEW_BAYESIAN_STATS_METHOD]

                    response = await api.create(`api/projects/${values.currentProjectId}/experiments`, {
                        ...values.experiment,
                        parameters:
                            /**
                             * only if we are creating a new experiment we need to reset
                             * the recommended running time. If we are duplicating we want to
                             * preserve this values.
                             */
                            props.formMode === FORM_MODES.create
                                ? {
                                      ...values.experiment?.parameters,
                                      recommended_running_time: recommendedRunningTime,
                                      recommended_sample_size: recommendedSampleSize,
                                      minimum_detectable_effect: minimumDetectableEffect,
                                  }
                                : values.experiment?.parameters,
                        // Set stats_config based on the feature flag if no existing stats_config
                        ...(useNewBayesianStatsMethod &&
                            !values.experiment.stats_config && {
                                stats_config: {
                                    method: ExperimentStatsMethod.Bayesian,
                                    use_new_bayesian_method: true,
                                },
                            }),
                        ...(!draft && { start_date: dayjs() }),
                        ...(typeof folder === 'string' ? { _create_in_folder: folder } : {}),
                    })

                    if (response) {
                        actions.reportExperimentCreated(response)
                        actions.addProductIntent({
                            product_type: ProductKey.EXPERIMENTS,
                            intent_context: ProductIntentContext.EXPERIMENT_CREATED,
                        })
                        if (response.feature_flag?.id) {
                            refreshTreeItem('feature_flag', String(response.feature_flag.id))
                        }
                    }
                }
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to create experiment')
                return
            }

            if (response?.id) {
                const experimentId = response.id
                refreshTreeItem('experiment', String(experimentId))
                router.actions.push(urls.experiment(experimentId))
                actions.addToExperiments(response)
                lemonToast.success(`Experiment ${isUpdate ? 'updated' : 'created'}`, {
                    button: {
                        label: 'View it',
                        action: () => {
                            router.actions.push(urls.experiment(experimentId))
                        },
                    },
                })
            }
        },
        setExperimentType: async ({ type }) => {
            actions.setExperiment({ type: type })
        },
        loadExperimentSuccess: async ({ experiment }) => {
            const duration = experiment?.start_date ? dayjs().diff(experiment.start_date, 'second') : null
            experiment && actions.reportExperimentViewed(experiment, duration)

            if (experiment?.start_date) {
                actions.refreshExperimentResults()
            }
        },
        launchExperiment: async () => {
            const startDate = dayjs()
            actions.updateExperiment({ start_date: startDate.toISOString() })
            values.experiment && eventUsageLogic.actions.reportExperimentLaunched(values.experiment, startDate)
            activationLogic.findMounted()?.actions.markTaskAsCompleted(ActivationTask.LaunchExperiment)
        },
        changeExperimentStartDate: async ({ startDate }) => {
            actions.updateExperiment({ start_date: startDate })
            values.experiment && eventUsageLogic.actions.reportExperimentStartDateChange(values.experiment, startDate)
        },
        changeExperimentEndDate: async ({ endDate }) => {
            actions.updateExperiment({ end_date: endDate })
            values.experiment && eventUsageLogic.actions.reportExperimentEndDateChange(values.experiment, endDate)
        },
        endExperiment: async () => {
            const endDate = dayjs()
            actions.updateExperiment({
                end_date: endDate.toISOString(),
                conclusion: values.experiment.conclusion,
                conclusion_comment: values.experiment.conclusion_comment,
            })
            const duration = endDate.diff(values.experiment?.start_date, 'second')
            values.experiment &&
                actions.reportExperimentCompleted(
                    values.experiment,
                    endDate,
                    duration,
                    values.isPrimaryMetricSignificant(0)
                )
            actions.closeStopExperimentModal()
        },
        archiveExperiment: async () => {
            actions.updateExperiment({ archived: true })
            values.experiment && actions.reportExperimentArchived(values.experiment)
        },
        refreshExperimentResults: async ({ forceRefresh }) => {
            actions.loadPrimaryMetricsResults(forceRefresh)
            actions.loadSecondaryMetricsResults(forceRefresh)
            actions.loadExposures(forceRefresh)
        },
        updateExperimentMetrics: async () => {
            actions.updateExperiment({
                metrics: values.experiment.metrics,
                metrics_secondary: values.experiment.metrics_secondary,
            })
        },
        updateExperimentCollectionGoal: async () => {
            const { recommendedRunningTime, recommendedSampleSize, minimumDetectableEffect } = values

            actions.updateExperiment({
                parameters: {
                    ...values.experiment?.parameters,
                    recommended_running_time: recommendedRunningTime,
                    recommended_sample_size: recommendedSampleSize,
                    minimum_detectable_effect: minimumDetectableEffect || 0,
                },
            })
        },
        updateExposureCriteria: async () => {
            actions.updateExperiment({
                exposure_criteria: {
                    ...values.experiment.exposure_criteria,
                },
            })
            actions.refreshExperimentResults(true)
        },
        resetRunningExperiment: async () => {
            actions.updateExperiment({
                start_date: null,
                end_date: null,
                archived: false,
                conclusion: null,
                conclusion_comment: null,
            })
            values.experiment && actions.reportExperimentReset(values.experiment)
            actions.setLegacyPrimaryMetricsResults([])
            actions.setLegacySecondaryMetricsResults([])
        },
        updateExperimentSuccess: async ({ experiment, payload }) => {
            actions.updateExperiments(experiment)
            if (experiment.start_date) {
                const forceRefresh = payload?.start_date !== undefined || payload?.end_date !== undefined
                actions.refreshExperimentResults(forceRefresh)
            }
        },
        createExposureCohortSuccess: ({ exposureCohort }) => {
            if (exposureCohort && exposureCohort.id !== 'new') {
                cohortsModel.actions.cohortCreated(exposureCohort)
                actions.reportExperimentExposureCohortCreated(values.experiment, exposureCohort)
                actions.setExperiment({ exposure_cohort: exposureCohort.id })
                lemonToast.success('Exposure cohort created successfully', {
                    button: {
                        label: 'View cohort',
                        action: () => router.actions.push(urls.cohort(exposureCohort.id)),
                    },
                })
            }
        },
        shipVariantSuccess: ({ payload }) => {
            lemonToast.success('The selected variant has been shipped')
            actions.closeShipVariantModal()
            if (payload.shouldStopExperiment && !values.isExperimentStopped) {
                actions.endExperiment()
            }
            actions.loadExperiment()
            actions.reportExperimentVariantShipped(values.experiment)
        },
        shipVariantFailure: ({ error }) => {
            lemonToast.error(error)
            actions.closeShipVariantModal()
        },
        updateExperimentVariantImages: async ({ variantPreviewMediaIds }) => {
            try {
                const updatedParameters = {
                    ...values.experiment.parameters,
                    variant_screenshot_media_ids: variantPreviewMediaIds,
                }
                await api.update(`api/projects/${values.currentProjectId}/experiments/${values.experimentId}`, {
                    parameters: updatedParameters,
                })
                actions.setExperiment({
                    parameters: updatedParameters,
                })
            } catch {
                lemonToast.error('Failed to update experiment variant images')
            }
        },
        updateDistribution: async ({ featureFlag }) => {
            const { created_at, id, ...flag } = featureFlag

            const preparedFlag = indexToVariantKeyFeatureFlagPayloads(flag)

            const savedFlag = await api.update(
                `api/projects/${values.currentProjectId}/feature_flags/${id}`,
                preparedFlag
            )

            const updatedFlag = variantKeyToIndexFeatureFlagPayloads(savedFlag)
            actions.updateFlag(updatedFlag)

            actions.updateExperiment({
                holdout_id: values.experiment.holdout_id,
            })
        },
        addSharedMetricsToExperiment: async ({ sharedMetricIds, metadata }) => {
            const existingMetricsIds = values.experiment.saved_metrics.map((sharedMetric) => ({
                id: sharedMetric.saved_metric,
                metadata: sharedMetric.metadata,
            }))

            const newMetricsIds = sharedMetricIds.map((id: SharedMetric['id']) => ({ id, metadata }))
            newMetricsIds.forEach((metricId) => {
                const metric = values.sharedMetrics.find((m: SharedMetric) => m.id === metricId.id)
                if (metric) {
                    actions.reportExperimentSharedMetricAssigned(values.experimentId, metric)
                }
            })
            const combinedMetricsIds = [...existingMetricsIds, ...newMetricsIds]

            await api.update(`api/projects/${values.currentProjectId}/experiments/${values.experimentId}`, {
                saved_metrics_ids: combinedMetricsIds,
            })

            actions.loadExperiment()
        },
        removeSharedMetricFromExperiment: async ({ sharedMetricId }) => {
            const sharedMetricsIds = values.experiment.saved_metrics
                .filter((sharedMetric) => sharedMetric.saved_metric !== sharedMetricId)
                .map((sharedMetric) => ({
                    id: sharedMetric.saved_metric,
                    metadata: sharedMetric.metadata,
                }))
            await api.update(`api/projects/${values.currentProjectId}/experiments/${values.experimentId}`, {
                saved_metrics_ids: sharedMetricsIds,
            })

            actions.loadExperiment()
        },
        createExperimentDashboard: async () => {
            actions.setIsCreatingExperimentDashboard(true)

            /**
             * create a query builder to transform the experiment metric into a query
             * that can be used to create an insight
             */
            const queryBuilder = compose<
                ExperimentMetric,
                ExperimentMetric,
                FunnelsQuery | TrendsQuery | undefined,
                InsightVizNode | undefined
            >(
                addExposureToMetric({
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    custom_name: 'Placeholder for experiment exposure',
                    properties: [],
                }),
                getQuery(),
                getInsight()
            )

            try {
                /**
                 * get the experiment url for the dashboard description
                 */
                const experimentUrl =
                    window.location.origin + addProjectIdIfMissing(urls.experiment(values.experimentId))

                /**
                 * create a new dashboard
                 */
                const dashboard: DashboardType = await api.create(
                    `api/environments/${teamLogic.values.currentTeamId}/dashboards/`,
                    {
                        name: 'Experiment: ' + values.experiment.name,
                        description: `Dashboard for [${experimentUrl}](${experimentUrl})`,
                        filters: {
                            date_from: values.experiment.start_date,
                            date_to: values.experiment.end_date,
                            properties: [],
                            breakdown_filter: {
                                breakdown: '$feature/' + values.experiment.feature_flag_key,
                                breakdown_type: 'event' as BreakdownType,
                            },
                        },
                    } as Partial<DashboardType>
                )

                /**
                 * create a new insight for each metric, either primary or secondary
                 * reverse the order of the metric because adding an insight to the dashboard
                 * places it at the beginning of the list
                 */
                for (const type of ['secondary', 'primary']) {
                    const singleMetrics =
                        type === 'secondary' ? values.experiment.metrics_secondary : values.experiment.metrics
                    const sharedMetrics = values.experiment?.saved_metrics.filter(
                        (sharedMetric) => sharedMetric.metadata.type === type
                    )
                    const metrics = [
                        ...singleMetrics,
                        ...sharedMetrics.map((m) => ({ name: m.name, ...m.query })),
                    ].reverse()

                    for (const query of metrics) {
                        const insightQuery = queryBuilder(query)

                        await api.create(`api/projects/${projectLogic.values.currentProjectId}/insights`, {
                            name: query.name || undefined,
                            query: insightQuery,
                            dashboards: [dashboard.id],
                        })
                    }
                }

                actions.reportExperimentDashboardCreated(values.experiment, dashboard.id)

                const dashboardUrl = window.location.origin + addProjectIdIfMissing(urls.dashboard(dashboard.id))
                actions.updateExperiment({
                    description:
                        (values.experiment.description ? values.experiment.description + `\n\n` : '') +
                        `Dashboard: [${dashboardUrl}](${dashboardUrl})`,
                })

                lemonToast.success('Dashboard created successfully', {
                    button: {
                        label: 'View dashboard',
                        action: () => router.actions.push(`/dashboard/${dashboard.id}`),
                    },
                })
            } catch (error: any) {
                if (!isBreakpoint(error)) {
                    const message = error.code && error.detail ? `${error.code}: ${error.detail}` : error
                    lemonToast.error(`Could not create dashboard: ${message}`)
                }
            }
            actions.setIsCreatingExperimentDashboard(false)
        },
        restoreUnmodifiedExperiment: () => {
            if (values.unmodifiedExperiment) {
                actions.setExperiment(structuredClone(values.unmodifiedExperiment))
            }
        },
        validateFeatureFlag: async ({ featureFlagKey }: { featureFlagKey: string }, breakpoint) => {
            await breakpoint(200)
            const response = await api.get(
                `api/projects/${values.currentProjectId}/feature_flags/?${toParams({ search: featureFlagKey })}`
            )
            const existingErrors = {
                // :KLUDGE: If there is no name error, we don't want to trigger the 'required' error early
                name: undefined,
                ...values.experimentErrors,
            }
            if (response.results.length > 0) {
                const matchingFlag = response.results.find((flag: FeatureFlagType) => flag.key === featureFlagKey)
                if (matchingFlag) {
                    let isValid
                    try {
                        isValid = featureFlagEligibleForExperiment(matchingFlag)
                    } catch {
                        isValid = false
                    }
                    actions.setValidExistingFeatureFlag(isValid ? matchingFlag : null)
                    actions.setFeatureFlagValidationError(
                        isValid ? '' : 'Existing feature flag is not eligible for experiments.'
                    )
                    actions.setExperimentManualErrors({
                        ...existingErrors,
                        feature_flag_key: values.featureFlagValidationError || undefined,
                    })
                    return
                }
            }

            actions.setValidExistingFeatureFlag(null)
            actions.setFeatureFlagValidationError(validateFeatureFlagKey(featureFlagKey) || '')
            actions.setExperimentManualErrors({
                ...existingErrors,
                feature_flag_key: values.featureFlagValidationError || undefined,
            })
        },
        touchExperimentField: ({ key }) => {
            // :KLUDGE: Persist the existing feature_flag_key validation when the field is blurred.
            if (key === 'feature_flag_key') {
                actions.setExperimentManualErrors({
                    feature_flag_key: values.featureFlagValidationError || undefined,
                })
            }
        },
        loadPrimaryMetricsResults: async ({ refresh }: { refresh?: boolean }) => {
            actions.setPrimaryMetricsResultsLoading(true)
            actions.setLegacyPrimaryMetricsResults([])
            actions.setPrimaryMetricsResults([])

            let metrics = values.experiment?.metrics
            const sharedMetrics = values.experiment?.saved_metrics
                .filter((sharedMetric) => sharedMetric.metadata.type === 'primary')
                .map((sharedMetric) => sharedMetric.query)
            if (sharedMetrics) {
                metrics = [...metrics, ...sharedMetrics]
            }

            await loadMetrics({
                metrics,
                experimentId: values.experimentId,
                refresh,
                onSetLegacyResults: actions.setLegacyPrimaryMetricsResults,
                onSetResults: actions.setPrimaryMetricsResults,
                onSetErrors: actions.setPrimaryMetricsResultsErrors,
                onTimeout: actions.reportExperimentMetricTimeout,
            })

            actions.setPrimaryMetricsResultsLoading(false)
        },
        loadSecondaryMetricsResults: async ({ refresh }: { refresh?: boolean }) => {
            actions.setSecondaryMetricsResultsLoading(true)
            actions.setLegacySecondaryMetricsResults([])
            actions.setSecondaryMetricsResults([])

            let secondaryMetrics = values.experiment?.metrics_secondary
            const sharedMetrics = values.experiment?.saved_metrics
                .filter((sharedMetric) => sharedMetric.metadata.type === 'secondary')
                .map((sharedMetric) => sharedMetric.query)
            if (sharedMetrics) {
                secondaryMetrics = [...secondaryMetrics, ...sharedMetrics]
            }

            await loadMetrics({
                metrics: secondaryMetrics,
                experimentId: values.experimentId,
                refresh,
                onSetLegacyResults: actions.setLegacySecondaryMetricsResults,
                onSetResults: actions.setSecondaryMetricsResults,
                onSetErrors: actions.setSecondaryMetricsResultsErrors,
                onTimeout: actions.reportExperimentMetricTimeout,
            })

            actions.setSecondaryMetricsResultsLoading(false)
        },
        openReleaseConditionsModal: () => {
            const numericFlagId = values.experiment.feature_flag?.id
            if (numericFlagId) {
                const logic = sceneFeatureFlagLogic.findMounted() || sceneFeatureFlagLogic({ id: numericFlagId })
                if (logic) {
                    logic.actions.loadFeatureFlag() // Access the loader through actions
                }
            }
        },
    })),
    loaders(({ actions, props, values }) => ({
        experiment: {
            loadExperiment: async () => {
                if (props.experimentId && props.experimentId !== 'new') {
                    try {
                        let response: Experiment = await api.get(
                            `api/projects/${values.currentProjectId}/experiments/${props.experimentId}`
                        )

                        /**
                         * if we are duplicating, we need to clear a lot of props to ensure that
                         * the experiment will be in draft mode and available for launch
                         */
                        if (props.formMode === FORM_MODES.duplicate) {
                            response = {
                                ...response,
                                name: `${response.name} (duplicate)`,
                                parameters: {
                                    ...response.parameters,
                                    feature_flag_variants: NEW_EXPERIMENT.parameters.feature_flag_variants,
                                },
                                feature_flag: undefined,
                                feature_flag_key: '',
                                archived: false,
                                start_date: undefined,
                                end_date: undefined,
                                conclusion: undefined,
                                conclusion_comment: undefined,
                                created_by: null,
                                created_at: null,
                                updated_at: null,
                            }
                        }

                        actions.setUnmodifiedExperiment(structuredClone(response))
                        return response
                    } catch (error: any) {
                        if (error.status === 404) {
                            actions.setExperimentMissing()
                        } else {
                            throw error
                        }
                    }
                }
                return NEW_EXPERIMENT
            },
            updateExperiment: async (update: Partial<Experiment>) => {
                const response: Experiment = await api.update(
                    `api/projects/${values.currentProjectId}/experiments/${values.experimentId}`,
                    update
                )
                refreshTreeItem('experiment', String(values.experimentId))
                actions.setUnmodifiedExperiment(structuredClone(response))
                return response
            },
        },
        exposureCohort: [
            null as CohortType | null,
            {
                createExposureCohort: async () => {
                    if (props.experimentId && props.experimentId !== 'new' && props.experimentId !== 'web') {
                        return (await api.experiments.createExposureCohort(props.experimentId)).cohort
                    }
                    return null
                },
            },
        ],
        featureFlag: [
            null as FeatureFlagType | null,
            {
                shipVariant: async ({ selectedVariantKey, shouldStopExperiment }) => {
                    if (!values.experiment.feature_flag) {
                        throw new Error('Experiment does not have a feature flag linked')
                    }

                    const currentFlagFilters = values.experiment.feature_flag?.filters
                    const newFilters = transformFiltersForWinningVariant(currentFlagFilters, selectedVariantKey)

                    await api.update(
                        `api/projects/${values.currentProjectId}/feature_flags/${values.experiment.feature_flag?.id}`,
                        { filters: newFilters }
                    )

                    return shouldStopExperiment
                },
            },
        ],
        exposures: [
            null as any,
            {
                loadExposures: async (refresh: boolean = false) => {
                    const { experiment, usesNewQueryRunner } = values

                    if (!usesNewQueryRunner) {
                        return
                    }

                    const query = setLatestVersionsOnQuery({
                        kind: NodeKind.ExperimentExposureQuery,
                        experiment_id: props.experimentId,
                        experiment_name: experiment.name,
                        exposure_criteria: experiment.exposure_criteria,
                        feature_flag: experiment.feature_flag,
                        start_date: experiment.start_date,
                        end_date: experiment.end_date,
                        holdout: experiment.holdout,
                    })
                    return await performQuery(query, undefined, refresh ? 'force_async' : 'async')
                },
            },
        ],
    })),
    selectors({
        props: [() => [(_, props) => props], (props) => props],
        experimentId: [
            () => [(_, props) => props.experimentId ?? 'new'],
            (experimentId): Experiment['id'] => experimentId,
        ],
        formMode: [() => [(_, props) => props.formMode], (action: FormModes) => action],
        getInsightType: [
            () => [],
            () =>
                (
                    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery | undefined
                ): InsightType => {
                    return metric &&
                        ((metric?.kind === NodeKind.ExperimentMetric &&
                            metric.metric_type === ExperimentMetricType.MEAN) ||
                            metric?.kind === NodeKind.ExperimentTrendsQuery)
                        ? InsightType.TRENDS
                        : InsightType.FUNNELS
                },
        ],
        getExperimentMetricType: [
            () => [],
            () =>
                (metric: ExperimentMetric | undefined): ExperimentMetricType => {
                    return metric?.metric_type || ExperimentMetricType.MEAN
                },
        ],
        isExperimentDraft: [
            (s) => [s.experiment],
            (experiment): boolean => {
                return !experiment?.start_date && !experiment?.end_date && !experiment?.archived
            },
        ],
        isExperimentRunning: [
            (s) => [s.experiment],
            (experiment): boolean => {
                return !!experiment?.start_date
            },
        ],
        isExperimentStopped: [
            (s) => [s.experiment],
            (experiment): boolean => {
                return (
                    !!experiment?.end_date &&
                    dayjs().isSameOrAfter(dayjs(experiment.end_date), 'day') &&
                    !experiment.archived
                )
            },
        ],
        breadcrumbs: [
            (s) => [s.experiment, s.experimentId],
            (experiment, experimentId): Breadcrumb[] => [
                {
                    key: Scene.Experiments,
                    name: 'Experiments',
                    path: urls.experiments(),
                },
                {
                    key: [Scene.Experiment, experimentId],
                    name: experiment?.name || '',
                    onRename: async (name: string) => {
                        // :KLUDGE: work around a type error when using asyncActions accessed via a callback passed to selectors()
                        const logic = experimentLogic({ experimentId })
                        await logic.asyncActions.updateExperiment({ name })
                    },
                },
            ],
        ],
        projectTreeRef: [
            () => [(_, props: ExperimentLogicProps) => props.experimentId],
            (experimentId): ProjectTreeRef => {
                return { type: 'experiment', ref: experimentId === 'new' ? null : String(experimentId) }
            },
        ],
        variants: [
            (s) => [s.experiment],
            (experiment): MultivariateFlagVariant[] => {
                return experiment?.parameters?.feature_flag_variants || []
            },
        ],
        experimentMathAggregationForTrends: [
            (s) => [s.experiment],
            (experiment) => (): PropertyMathType | CountPerActorMathType | undefined => {
                const query = experiment?.metrics?.[0] as ExperimentTrendsQuery
                if (!query) {
                    return undefined
                }
                const entities = query.count_query?.series || []

                // Find out if we're using count per actor math aggregates averages per user
                const userMathValue = entities.filter((entity) =>
                    Object.values(CountPerActorMathType).includes(entity?.math as CountPerActorMathType)
                )[0]?.math

                // alternatively, if we're using property math
                // remove 'sum' property math from the list of math types
                // since we can handle that as a regular case
                const targetValues = Object.values(PropertyMathType).filter((value) => value !== PropertyMathType.Sum)

                const propertyMathValue = entities.filter((entity) =>
                    (targetValues as readonly PropertyMathType[]).includes(entity?.math as PropertyMathType)
                )[0]?.math

                return (userMathValue ?? propertyMathValue) as PropertyMathType | CountPerActorMathType | undefined
            },
        ],
        minimumDetectableEffect: [
            (s) => [s.experiment],
            (newExperiment): number => {
                return newExperiment?.parameters?.minimum_detectable_effect ?? DEFAULT_MDE
            },
        ],
        isPrimaryMetricSignificant: [
            (s) => [s.legacyPrimaryMetricsResults],
            (
                    legacyPrimaryMetricsResults: (
                        | CachedLegacyExperimentQueryResponse
                        | CachedExperimentFunnelsQueryResponse
                        | CachedExperimentTrendsQueryResponse
                        | null
                    )[]
                ) =>
                (metricIndex: number = 0): boolean => {
                    const result = legacyPrimaryMetricsResults?.[metricIndex]
                    if (!result) {
                        return false
                    }

                    return result.significant || false
                },
        ],
        isSecondaryMetricSignificant: [
            (s) => [s.legacySecondaryMetricsResults],
            (
                    legacySecondaryMetricsResults: (
                        | CachedLegacyExperimentQueryResponse
                        | CachedExperimentFunnelsQueryResponse
                        | CachedExperimentTrendsQueryResponse
                        | null
                    )[]
                ) =>
                (metricIndex: number = 0): boolean => {
                    const result = legacySecondaryMetricsResults?.[metricIndex]
                    if (!result) {
                        return false
                    }

                    return result.significant || false
                },
        ],
        significanceDetails: [
            (s) => [s.legacyPrimaryMetricsResults],
            (
                    legacyPrimaryMetricsResults: (
                        | CachedLegacyExperimentQueryResponse
                        | CachedExperimentFunnelsQueryResponse
                        | CachedExperimentTrendsQueryResponse
                        | null
                    )[]
                ) =>
                (metricIndex: number = 0): string => {
                    const results = legacyPrimaryMetricsResults?.[metricIndex]
                    return getSignificanceDetails(results)
                },
        ],
        recommendedSampleSize: [
            (s) => [s.conversionMetrics, s.variants, s.minimumDetectableEffect],
            (conversionMetrics, variants, minimumDetectableEffect): number => {
                const conversionRate = conversionMetrics.totalRate * 100
                const sampleSizePerVariant = minimumSampleSizePerVariant(minimumDetectableEffect, conversionRate)
                const sampleSize = sampleSizePerVariant * variants.length
                return sampleSize
            },
        ],
        recommendedRunningTime: [
            (s) => [
                s.experiment,
                s.variants,
                s.getInsightType,
                s.firstPrimaryMetric,
                s.funnelResults,
                s.conversionMetrics,
                s.trendResults,
                s.minimumDetectableEffect,
            ],
            (
                experiment,
                variants,
                getInsightType,
                firstPrimaryMetric,
                funnelResults,
                conversionMetrics,
                trendResults,
                minimumDetectableEffect
            ): number => {
                if (getInsightType(firstPrimaryMetric) === InsightType.FUNNELS) {
                    const currentDuration = dayjs().diff(dayjs(experiment?.start_date), 'hour')
                    let funnelEntrants: number | undefined
                    if (Array.isArray(funnelResults) && funnelResults[0]) {
                        const firstFunnelEntry = funnelResults[0]

                        funnelEntrants = Array.isArray(firstFunnelEntry)
                            ? firstFunnelEntry[0].count
                            : firstFunnelEntry.count
                    }

                    const conversionRate = conversionMetrics.totalRate * 100
                    const sampleSizePerVariant = minimumSampleSizePerVariant(minimumDetectableEffect, conversionRate)
                    const funnelSampleSize = sampleSizePerVariant * variants.length
                    if (experiment?.start_date) {
                        return expectedRunningTime(funnelEntrants || 1, funnelSampleSize || 0, currentDuration)
                    }
                    return expectedRunningTime(funnelEntrants || 1, funnelSampleSize || 0)
                }

                const trendCount = trendResults[0]?.count
                const runningTime = recommendedExposureForCountData(minimumDetectableEffect, trendCount)
                return runningTime
            },
        ],
        tabularExperimentResults: [
            (s) => [s.experiment, s.legacyPrimaryMetricsResults, s.legacySecondaryMetricsResults, s.getInsightType],
            (
                    experiment,
                    legacyPrimaryMetricsResults: (
                        | CachedLegacyExperimentQueryResponse
                        | CachedExperimentFunnelsQueryResponse
                        | CachedExperimentTrendsQueryResponse
                        | null
                    )[],
                    legacySecondaryMetricsResults: (
                        | CachedLegacyExperimentQueryResponse
                        | CachedExperimentFunnelsQueryResponse
                        | CachedExperimentTrendsQueryResponse
                        | null
                    )[],
                    getInsightType
                ) =>
                (metricIndex: number = 0, isSecondary: boolean = false): any[] => {
                    const tabularResults = []
                    const metricType = isSecondary
                        ? getInsightType(experiment.metrics_secondary[metricIndex])
                        : getInsightType(experiment.metrics[metricIndex])
                    const result = isSecondary
                        ? legacySecondaryMetricsResults[metricIndex]
                        : legacyPrimaryMetricsResults[metricIndex]

                    if (result) {
                        for (const variantObj of result.variants) {
                            if (metricType === InsightType.FUNNELS) {
                                const { key, success_count, failure_count } = variantObj as FunnelExperimentVariant
                                tabularResults.push({ key, success_count, failure_count })
                            } else if (metricType === InsightType.TRENDS) {
                                const { key, count, exposure, absolute_exposure } = variantObj as TrendExperimentVariant
                                tabularResults.push({ key, count, exposure, absolute_exposure })
                            }
                        }
                    }

                    if (experiment.feature_flag?.filters.multivariate?.variants) {
                        for (const { key } of experiment.feature_flag.filters.multivariate.variants) {
                            if (tabularResults.find((variantObj) => variantObj.key === key)) {
                                continue
                            }

                            if (metricType === InsightType.FUNNELS) {
                                tabularResults.push({ key, success_count: null, failure_count: null })
                            } else if (metricType === InsightType.TRENDS) {
                                tabularResults.push({ key, count: null, exposure: null, absolute_exposure: null })
                            }
                        }
                    }

                    return tabularResults
                },
        ],
        sortedWinProbabilities: [
            (s) => [s.legacyPrimaryMetricsResults],
            (
                    legacyPrimaryMetricsResults: (
                        | CachedLegacyExperimentQueryResponse
                        | CachedExperimentFunnelsQueryResponse
                        | CachedExperimentTrendsQueryResponse
                        | null
                    )[]
                ) =>
                (metricIndex: number = 0) => {
                    const result = legacyPrimaryMetricsResults?.[metricIndex]

                    if (!result) {
                        return []
                    }

                    return Object.keys(result.probability)
                        .map((key) => ({
                            key,
                            winProbability: result.probability[key],
                            conversionRate: conversionRateForVariant(result, key),
                        }))
                        .sort((a, b) => b.winProbability - a.winProbability)
                },
        ],
        funnelResultsPersonsTotal: [
            (s) => [s.experiment, s.legacyPrimaryMetricsResults, s.getInsightType],
            (
                    experiment,
                    legacyPrimaryMetricsResults: (
                        | CachedLegacyExperimentQueryResponse
                        | CachedExperimentFunnelsQueryResponse
                        | CachedExperimentTrendsQueryResponse
                        | null
                    )[],
                    getInsightType
                ) =>
                (metricIndex: number = 0): number => {
                    const result = legacyPrimaryMetricsResults?.[metricIndex]

                    if (getInsightType(experiment.metrics[metricIndex]) !== InsightType.FUNNELS || !result) {
                        return 0
                    }

                    let sum = 0
                    result.insight.forEach((variantResult) => {
                        if (variantResult[0]?.count) {
                            sum += variantResult[0].count
                        }
                    })
                    return sum
                },
        ],
        actualRunningTime: [
            (s) => [s.experiment],
            (experiment: Experiment): number => {
                if (!experiment.start_date) {
                    return 0
                }

                if (experiment.end_date) {
                    return dayjs(experiment.end_date).diff(experiment.start_date, 'day')
                }

                return dayjs().diff(experiment.start_date, 'day')
            },
        ],
        isSingleVariantShipped: [
            (s) => [s.experiment],
            (experiment: Experiment): boolean => {
                const filters = experiment.feature_flag?.filters

                return (
                    !!filters &&
                    Array.isArray(filters.groups?.[0]?.properties) &&
                    filters.groups?.[0]?.properties?.length === 0 &&
                    filters.groups?.[0]?.rollout_percentage === 100 &&
                    (filters.multivariate?.variants?.some(({ rollout_percentage }) => rollout_percentage === 100) ||
                        false)
                )
            },
        ],
        hasPrimaryMetricSet: [
            (s) => [s.primaryMetricsLengthWithSharedMetrics],
            (primaryMetricsLengthWithSharedMetrics): boolean => {
                return primaryMetricsLengthWithSharedMetrics > 0
            },
        ],
        firstPrimaryMetric: [
            (s) => [s.experiment],
            (experiment: Experiment): ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery | undefined => {
                if (experiment.metrics.length) {
                    return experiment.metrics[0]
                }
                const primaryMetric = experiment.saved_metrics.find((metric) => metric.metadata.type === 'primary')
                if (primaryMetric) {
                    return primaryMetric.query
                }
            },
        ],
        primaryMetricsLengthWithSharedMetrics: [
            (s) => [s.experiment],
            (experiment: Experiment): number => {
                return (
                    experiment.metrics.length +
                    experiment.saved_metrics.filter((savedMetric) => savedMetric.metadata.type === 'primary').length
                )
            },
        ],
        secondaryMetricsLengthWithSharedMetrics: [
            (s) => [s.experiment],
            (experiment: Experiment): number => {
                return (
                    experiment.metrics_secondary.length +
                    experiment.saved_metrics.filter((savedMetric) => savedMetric.metadata.type === 'secondary').length
                )
            },
        ],
        compatibleSharedMetrics: [
            (s) => [s.sharedMetrics, s.usesNewQueryRunner],
            (sharedMetrics: SharedMetric[], usesNewQueryRunner: boolean): SharedMetric[] => {
                if (!sharedMetrics) {
                    return []
                }
                if (usesNewQueryRunner) {
                    return sharedMetrics.filter((metric) => metric.query.kind === NodeKind.ExperimentMetric)
                }
                return sharedMetrics.filter((metric) => metric.query.kind !== NodeKind.ExperimentMetric)
            },
        ],
        usesNewQueryRunner: [
            (s) => [s.experiment],
            (experiment: Experiment): boolean => {
                const hasLegacyMetrics = isLegacyExperiment(experiment)

                const allMetrics = [...experiment.metrics, ...experiment.metrics_secondary, ...experiment.saved_metrics]
                const hasExperimentMetrics = allMetrics.some((query) => query.kind === NodeKind.ExperimentMetric)

                if (hasExperimentMetrics) {
                    return true
                }

                if (hasLegacyMetrics) {
                    return false
                }

                // If the experiment has no experiment metrics, we use the new query runner
                return true
            },
        ],
        hasMinimumExposureForResults: [
            (s) => [s.exposures, s.usesNewQueryRunner],
            (exposures: ExperimentExposureQueryResponse, usesNewQueryRunner: boolean): boolean => {
                // Not relevant for old metrics
                if (!usesNewQueryRunner) {
                    return true
                }

                if (!exposures || !exposures.total_exposures) {
                    return false
                }

                const total_experiment_exposures = Object.values(exposures.total_exposures).reduce(
                    (acc, curr) => acc + curr,
                    0
                )

                if (total_experiment_exposures < EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS) {
                    return false
                }

                return true
            },
        ],
        exposureCriteria: [
            (s) => [s.experiment],
            (experiment: Experiment): ExperimentExposureCriteria | undefined => {
                return experiment.exposure_criteria
            },
        ],
        statsMethod: [
            (s) => [s.experiment],
            (experiment: Experiment): ExperimentStatsMethod => {
                return experiment.stats_config?.method || ExperimentStatsMethod.Bayesian
            },
        ],
    }),
    forms(({ actions, values, props }) => ({
        experiment: {
            options: { showErrorsOnTouch: true },
            defaults: { ...NEW_EXPERIMENT } as Experiment,
            errors: ({ name, parameters }) => ({
                name: !name && 'Please enter a name',
                // feature_flag_key is handled asynchronously
                parameters: {
                    feature_flag_variants: parameters.feature_flag_variants?.map(({ key }) => ({
                        key: !key.match?.(/^([A-z]|[a-z]|[0-9]|-|_)+$/)
                            ? 'Only letters, numbers, hyphens (-) & underscores (_) are allowed.'
                            : undefined,
                    })),
                },
            }),
            submit: () => {
                if (
                    values.experimentId &&
                    ([FORM_MODES.create, FORM_MODES.duplicate] as FormModes[]).includes(props.formMode!)
                ) {
                    actions.createExperiment(true)
                } else {
                    actions.createExperiment(true, 'Unfiled/Experiments')
                }
            },
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/experiments/:id': ({ id }, query, __, currentLocation, previousLocation) => {
            const didPathChange = currentLocation.initial || currentLocation.pathname !== previousLocation?.pathname

            actions.setEditExperiment(false)

            if (id && didPathChange) {
                const parsedId = id === 'new' ? 'new' : parseInt(id)
                if (parsedId === 'new') {
                    actions.resetExperiment({
                        ...NEW_EXPERIMENT,
                        metrics: query.metric ? [query.metric] : [],
                        name: query.name ?? '',
                    })
                }
                if (parsedId !== 'new' && parsedId === values.experimentId) {
                    actions.loadExperiment()
                    if (values.isExperimentRunning) {
                        actions.loadExposures()
                    }
                }
            }
        },
        '/experiments/:id/:formMode': ({ id }, _, __, currentLocation, previousLocation) => {
            const didPathChange = currentLocation.initial || currentLocation.pathname !== previousLocation?.pathname

            if (id && didPathChange) {
                actions.loadExperiment()
            }
        },
    })),
])
