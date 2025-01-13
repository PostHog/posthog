import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { EXPERIMENT_DEFAULT_DURATION, FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { hasFormErrors, toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import {
    indexToVariantKeyFeatureFlagPayloads,
    variantKeyToIndexFeatureFlagPayloads,
} from 'scenes/feature-flags/featureFlagLogic'
import { validateFeatureFlagKey } from 'scenes/feature-flags/featureFlagLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { cleanFilters, getDefaultEvent } from 'scenes/insights/utils/cleanFilters'
import { projectLogic } from 'scenes/projectLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { performQuery } from '~/queries/query'
import {
    CachedExperimentFunnelsQueryResponse,
    CachedExperimentTrendsQueryResponse,
    ExperimentFunnelsQuery,
    ExperimentSignificanceCode,
    ExperimentTrendsQuery,
    NodeKind,
} from '~/queries/schema'
import {
    Breadcrumb,
    BreakdownAttributionType,
    ChartDisplayType,
    CohortType,
    CountPerActorMathType,
    EntityTypes,
    Experiment,
    ExperimentResults,
    FeatureFlagType,
    FilterType,
    FunnelConversionWindowTimeUnit,
    FunnelExperimentVariant,
    FunnelStep,
    FunnelVizType,
    InsightType,
    MultivariateFlagVariant,
    ProductKey,
    PropertyMathType,
    TrendExperimentVariant,
    TrendResult,
    TrendsFilterType,
} from '~/types'

import { MetricInsightId } from './constants'
import type { experimentLogicType } from './experimentLogicType'
import { experimentsLogic } from './experimentsLogic'
import { holdoutsLogic } from './holdoutsLogic'
import { SharedMetric } from './SharedMetrics/sharedMetricLogic'
import { sharedMetricsLogic } from './SharedMetrics/sharedMetricsLogic'
import { getMinimumDetectableEffect, transformFiltersForWinningVariant } from './utils'

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
}

export interface ExperimentLogicProps {
    experimentId?: Experiment['id']
}

interface SecondaryMetricResult {
    insightType: InsightType
    result?: number
}

export interface TabularSecondaryMetricResults {
    variant: string
    results?: SecondaryMetricResult[]
}

export interface ExperimentResultCalculationError {
    detail: string
    statusCode: number
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
            ],
            teamLogic,
            ['addProductIntent'],
            featureFlagsLogic,
            ['updateFlag'],
        ],
    })),
    actions({
        setExperimentMissing: true,
        setExperiment: (experiment: Partial<Experiment>) => ({ experiment }),
        createExperiment: (draft?: boolean) => ({ draft }),
        setExperimentType: (type?: string) => ({ type }),
        removeExperimentGroup: (idx: number) => ({ idx }),
        setEditExperiment: (editing: boolean) => ({ editing }),
        setFlagImplementationWarning: (warning: boolean) => ({ warning }),
        setExposureAndSampleSize: (exposure: number, sampleSize: number) => ({ exposure, sampleSize }),
        updateExperimentGoal: true,
        updateExperimentCollectionGoal: true,
        changeExperimentStartDate: (startDate: string) => ({ startDate }),
        setExperimentStatsVersion: (version: number) => ({ version }),
        launchExperiment: true,
        endExperiment: true,
        addExperimentGroup: true,
        archiveExperiment: true,
        resetRunningExperiment: true,
        checkFlagImplementationWarning: true,
        openExperimentCollectionGoalModal: true,
        closeExperimentCollectionGoalModal: true,
        openShipVariantModal: true,
        closeShipVariantModal: true,
        openDistributionModal: true,
        closeDistributionModal: true,
        openReleaseConditionsModal: true,
        closeReleaseConditionsModal: true,
        updateExperimentVariantImages: (variantPreviewMediaIds: Record<string, string[]>) => ({
            variantPreviewMediaIds,
        }),
        setTrendsMetric: ({
            metricIdx,
            name,
            series,
            filterTestAccounts,
            isSecondary = false,
        }: {
            metricIdx: number
            name?: string
            series?: any[]
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
            series?: any[]
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
            series?: any[]
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
        setTabKey: (tabKey: string) => ({ tabKey }),
        openPrimaryMetricModal: (index: number) => ({ index }),
        closePrimaryMetricModal: true,
        setPrimaryMetricsResultErrors: (errors: any[]) => ({ errors }),
        setEditingPrimaryMetricIndex: (index: number | null) => ({ index }),
        updateDistributionModal: (featureFlag: FeatureFlagType) => ({ featureFlag }),
        openSecondaryMetricModal: (index: number) => ({ index }),
        closeSecondaryMetricModal: true,
        setSecondaryMetricsResultErrors: (errors: any[]) => ({ errors }),
        openPrimaryMetricSourceModal: true,
        closePrimaryMetricSourceModal: true,
        openSecondaryMetricSourceModal: true,
        closeSecondaryMetricSourceModal: true,
        openPrimarySharedMetricModal: (sharedMetricId: SharedMetric['id'] | null) => ({ sharedMetricId }),
        closePrimarySharedMetricModal: true,
        openSecondarySharedMetricModal: (sharedMetricId: SharedMetric['id'] | null) => ({ sharedMetricId }),
        closeSecondarySharedMetricModal: true,
        addSharedMetricToExperiment: (
            sharedMetricId: SharedMetric['id'],
            metadata: { type: 'primary' | 'secondary' }
        ) => ({
            sharedMetricId,
            metadata,
        }),
        removeSharedMetricFromExperiment: (sharedMetricId: SharedMetric['id']) => ({ sharedMetricId }),
    }),
    reducers({
        experiment: [
            { ...NEW_EXPERIMENT } as Experiment,
            {
                setExperiment: (state, { experiment }) => {
                    return { ...state, ...experiment }
                },
                addExperimentGroup: (state) => {
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
                removeExperimentGroup: (state, { idx }) => {
                    if (!state) {
                        return state
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
            },
        ],
        experimentMissing: [
            false,
            {
                setExperimentMissing: () => true,
            },
        ],
        editingExistingExperiment: [
            false,
            {
                setEditExperiment: (_, { editing }) => editing,
            },
        ],
        flagImplementationWarning: [
            false as boolean,
            {
                setFlagImplementationWarning: (_, { warning }) => warning,
            },
        ],
        isExperimentCollectionGoalModalOpen: [
            false,
            {
                openExperimentCollectionGoalModal: () => true,
                closeExperimentCollectionGoalModal: () => false,
            },
        ],
        isShipVariantModalOpen: [
            false,
            {
                openShipVariantModal: () => true,
                closeShipVariantModal: () => false,
            },
        ],
        isDistributionModalOpen: [
            false,
            {
                openDistributionModal: () => true,
                closeDistributionModal: () => false,
            },
        ],
        isReleaseConditionsModalOpen: [
            false,
            {
                openReleaseConditionsModal: () => true,
                closeReleaseConditionsModal: () => false,
            },
        ],
        experimentValuesChangedLocally: [
            false,
            {
                setExperiment: () => true,
                loadExperiment: () => false,
                updateExperiment: () => false,
            },
        ],
        tabKey: [
            'results',
            {
                setTabKey: (_, { tabKey }) => tabKey,
            },
        ],
        isPrimaryMetricModalOpen: [
            false,
            {
                openPrimaryMetricModal: () => true,
                closePrimaryMetricModal: () => false,
            },
        ],
        editingPrimaryMetricIndex: [
            null as number | null,
            {
                openPrimaryMetricModal: (_, { index }) => index,
                closePrimaryMetricModal: () => null,
                updateExperimentGoal: () => null,
                setEditingPrimaryMetricIndex: (_, { index }) => index,
            },
        ],
        primaryMetricsResultErrors: [
            [] as any[],
            {
                setPrimaryMetricsResultErrors: (_, { errors }) => errors,
                loadMetricResults: () => [],
                loadExperiment: () => [],
            },
        ],
        isSecondaryMetricModalOpen: [
            false,
            {
                openSecondaryMetricModal: () => true,
                closeSecondaryMetricModal: () => false,
            },
        ],
        editingSecondaryMetricIndex: [
            null as number | null,
            {
                openSecondaryMetricModal: (_, { index }) => index,
                closeSecondaryMetricModal: () => null,
                updateExperimentGoal: () => null,
            },
        ],
        editingSharedMetricId: [
            null as SharedMetric['id'] | null,
            {
                openPrimarySharedMetricModal: (_, { sharedMetricId }) => sharedMetricId,
                openSecondarySharedMetricModal: (_, { sharedMetricId }) => sharedMetricId,
                closePrimarySharedMetricModal: () => null,
                closeSecondarySharedMetricModal: () => null,
                updateExperimentGoal: () => null,
            },
        ],
        secondaryMetricsResultErrors: [
            [] as any[],
            {
                setSecondaryMetricsResultErrors: (_, { errors }) => errors,
                loadSecondaryMetricResults: () => [],
                loadExperiment: () => [],
            },
        ],
        isPrimaryMetricSourceModalOpen: [
            false,
            {
                openPrimaryMetricSourceModal: () => true,
                closePrimaryMetricSourceModal: () => false,
            },
        ],
        isSecondaryMetricSourceModalOpen: [
            false,
            {
                openSecondaryMetricSourceModal: () => true,
                closeSecondaryMetricSourceModal: () => false,
            },
        ],
        isPrimarySharedMetricModalOpen: [
            false,
            {
                openPrimarySharedMetricModal: () => true,
                closePrimarySharedMetricModal: () => false,
            },
        ],
        isSecondarySharedMetricModalOpen: [
            false,
            {
                openSecondarySharedMetricModal: () => true,
                closeSecondarySharedMetricModal: () => false,
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        createExperiment: async ({ draft }) => {
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
            const isUpdate = !!values.experimentId && values.experimentId !== 'new'
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
                    response = await api.create(`api/projects/${values.currentProjectId}/experiments`, {
                        ...values.experiment,
                        parameters: {
                            ...values.experiment?.parameters,
                            recommended_running_time: recommendedRunningTime,
                            recommended_sample_size: recommendedSampleSize,
                            minimum_detectable_effect: minimumDetectableEffect,
                        },
                        ...(!draft && { start_date: dayjs() }),
                    })
                    if (response) {
                        actions.reportExperimentCreated(response)
                        actions.addProductIntent({ product_type: ProductKey.EXPERIMENTS })
                    }
                }
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to create experiment')
                return
            }

            if (response?.id) {
                const experimentId = response.id
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
            experiment && actions.reportExperimentViewed(experiment)

            if (experiment?.start_date) {
                actions.loadMetricResults()
                actions.loadSecondaryMetricResults()
            }
        },
        launchExperiment: async () => {
            const startDate = dayjs()
            actions.updateExperiment({ start_date: startDate.toISOString() })
            values.experiment && eventUsageLogic.actions.reportExperimentLaunched(values.experiment, startDate)
        },
        changeExperimentStartDate: async ({ startDate }) => {
            actions.updateExperiment({ start_date: startDate })
            values.experiment && eventUsageLogic.actions.reportExperimentStartDateChange(values.experiment, startDate)
        },
        setExperimentStatsVersion: async ({ version }, breakpoint) => {
            actions.updateExperiment({ stats_config: { version } })
            await breakpoint(100)
            if (values.experiment?.start_date) {
                actions.loadMetricResults(true)
                actions.loadSecondaryMetricResults(true)
            }
        },
        endExperiment: async () => {
            const endDate = dayjs()
            actions.updateExperiment({ end_date: endDate.toISOString() })
            const duration = endDate.diff(values.experiment?.start_date, 'second')
            values.experiment &&
                actions.reportExperimentCompleted(
                    values.experiment,
                    endDate,
                    duration,
                    values.isPrimaryMetricSignificant(0)
                )
        },
        archiveExperiment: async () => {
            actions.updateExperiment({ archived: true })
            values.experiment && actions.reportExperimentArchived(values.experiment)
        },
        updateExperimentGoal: async () => {
            // Reset MDE to the recommended setting
            actions.setExperiment({
                parameters: {
                    ...values.experiment.parameters,
                    minimum_detectable_effect: undefined,
                },
            })

            const { recommendedRunningTime, recommendedSampleSize, minimumDetectableEffect } = values

            actions.updateExperiment({
                metrics: values.experiment.metrics,
                metrics_secondary: values.experiment.metrics_secondary,
                parameters: {
                    ...values.experiment?.parameters,
                    recommended_running_time: recommendedRunningTime,
                    recommended_sample_size: recommendedSampleSize,
                    minimum_detectable_effect: minimumDetectableEffect,
                },
            })
            actions.closePrimaryMetricModal()
            actions.closeSecondaryMetricModal()
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
            actions.closeExperimentCollectionGoalModal()
        },
        closeExperimentCollectionGoalModal: () => {
            if (values.experimentValuesChangedLocally) {
                actions.loadExperiment()
            }
        },
        resetRunningExperiment: async () => {
            actions.updateExperiment({ start_date: null, end_date: null, archived: false })
            values.experiment && actions.reportExperimentReset(values.experiment)
            actions.loadMetricResultsSuccess([])
            actions.loadSecondaryMetricResultsSuccess([])
        },
        updateExperimentSuccess: async ({ experiment, payload }) => {
            actions.updateExperiments(experiment)
            if (experiment.start_date) {
                const forceRefresh = payload?.start_date !== undefined
                actions.loadMetricResults(forceRefresh)
                actions.loadSecondaryMetricResults(forceRefresh)
            }
        },
        setExperiment: async ({ experiment }) => {
            const experimentEntitiesChanged =
                (experiment.filters?.events && experiment.filters.events.length > 0) ||
                (experiment.filters?.actions && experiment.filters.actions.length > 0) ||
                (experiment.filters?.data_warehouse && experiment.filters.data_warehouse.length > 0)

            if (!experiment.filters || Object.keys(experiment.filters).length === 0) {
                return
            }

            if (experimentEntitiesChanged) {
                actions.checkFlagImplementationWarning()
            }
        },
        setExperimentValue: async ({ name, value }, breakpoint) => {
            await breakpoint(100)

            if (name === 'filters') {
                const experimentEntitiesChanged =
                    (value?.events && value.events.length > 0) ||
                    (value?.actions && value.actions.length > 0) ||
                    (value?.data_warehouse && value.data_warehouse.length > 0)

                if (!value || Object.keys(value).length === 0) {
                    return
                }

                if (experimentEntitiesChanged) {
                    actions.checkFlagImplementationWarning()
                }
            }
        },
        setExperimentValues: async ({ values }, breakpoint) => {
            await breakpoint(100)

            const experiment = values

            const experimentEntitiesChanged =
                (experiment.filters?.events && experiment.filters.events.length > 0) ||
                (experiment.filters?.actions && experiment.filters.actions.length > 0) ||
                (experiment.filters?.data_warehouse && experiment.filters.data_warehouse.length > 0)

            if (!experiment.filters || Object.keys(experiment.filters).length === 0) {
                return
            }

            if (experimentEntitiesChanged) {
                actions.checkFlagImplementationWarning()
            }
        },
        checkFlagImplementationWarning: async (_, breakpoint) => {
            const experiment = values.experiment
            const experimentEntitiesChanged =
                (experiment.filters?.events && experiment.filters.events.length > 0) ||
                (experiment.filters?.actions && experiment.filters.actions.length > 0) ||
                (experiment.filters?.data_warehouse && experiment.filters.data_warehouse.length > 0)

            if (!experiment.filters || Object.keys(experiment.filters).length === 0) {
                return
            }

            if (experimentEntitiesChanged) {
                const url = `/api/projects/${
                    values.currentProjectId
                }/experiments/requires_flag_implementation?${toParams(experiment.filters || {})}`
                await breakpoint(100)

                try {
                    const response = await api.get(url)
                    actions.setFlagImplementationWarning(response.result)
                } catch (e) {
                    // default to not showing the warning
                    actions.setFlagImplementationWarning(false)
                }
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
            } catch (error) {
                lemonToast.error('Failed to update experiment variant images')
            }
        },
        updateDistributionModal: async ({ featureFlag }) => {
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
        addSharedMetricToExperiment: async ({ sharedMetricId, metadata }) => {
            const sharedMetricsIds = values.experiment.saved_metrics.map((sharedMetric) => ({
                id: sharedMetric.saved_metric,
                metadata,
            }))
            sharedMetricsIds.push({ id: sharedMetricId, metadata })

            await api.update(`api/projects/${values.currentProjectId}/experiments/${values.experimentId}`, {
                saved_metrics_ids: sharedMetricsIds,
            })

            actions.closePrimarySharedMetricModal()
            actions.closeSecondarySharedMetricModal()
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

            actions.closePrimarySharedMetricModal()
            actions.closeSecondarySharedMetricModal()
            actions.loadExperiment()
        },
    })),
    loaders(({ actions, props, values }) => ({
        experiment: {
            loadExperiment: async () => {
                if (props.experimentId && props.experimentId !== 'new') {
                    try {
                        const response = await api.get(
                            `api/projects/${values.currentProjectId}/experiments/${props.experimentId}`
                        )
                        return response as Experiment
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
                return response
            },
        },
        metricResults: [
            null as (CachedExperimentTrendsQueryResponse | CachedExperimentFunnelsQueryResponse | null)[] | null,
            {
                loadMetricResults: async (
                    refresh?: boolean
                ): Promise<(CachedExperimentTrendsQueryResponse | CachedExperimentFunnelsQueryResponse | null)[]> => {
                    let metrics = values.experiment?.metrics
                    const sharedMetrics = values.experiment?.saved_metrics
                        .filter((sharedMetric) => sharedMetric.metadata.type === 'primary')
                        .map((sharedMetric) => sharedMetric.query)
                    if (sharedMetrics) {
                        metrics = [...metrics, ...sharedMetrics]
                    }

                    return (await Promise.all(
                        metrics.map(async (metric, index) => {
                            try {
                                const queryWithExperimentId = {
                                    ...metric,
                                    experiment_id: values.experimentId,
                                }
                                const response = await performQuery(queryWithExperimentId, undefined, refresh)

                                return {
                                    ...response,
                                    fakeInsightId: Math.random().toString(36).substring(2, 15),
                                }
                            } catch (error: any) {
                                const errorDetailMatch = error.detail.match(/\{.*\}/)
                                const errorDetail = errorDetailMatch ? JSON.parse(errorDetailMatch[0]) : error.detail

                                const currentErrors = [...(values.primaryMetricsResultErrors || [])]
                                currentErrors[index] = {
                                    detail: errorDetail,
                                    statusCode: error.status,
                                    hasDiagnostics: !!errorDetailMatch,
                                }
                                actions.setPrimaryMetricsResultErrors(currentErrors)
                                return null
                            }
                        })
                    )) as (CachedExperimentTrendsQueryResponse | CachedExperimentFunnelsQueryResponse | null)[]
                },
            },
        ],
        secondaryMetricResults: [
            null as (CachedExperimentTrendsQueryResponse | CachedExperimentFunnelsQueryResponse | null)[] | null,
            {
                loadSecondaryMetricResults: async (
                    refresh?: boolean
                ): Promise<(CachedExperimentTrendsQueryResponse | CachedExperimentFunnelsQueryResponse | null)[]> => {
                    let metrics = values.experiment?.metrics_secondary
                    const sharedMetrics = values.experiment?.saved_metrics
                        .filter((sharedMetric) => sharedMetric.metadata.type === 'secondary')
                        .map((sharedMetric) => sharedMetric.query)
                    if (sharedMetrics) {
                        metrics = [...metrics, ...sharedMetrics]
                    }

                    return (await Promise.all(
                        metrics.map(async (metric, index) => {
                            try {
                                const queryWithExperimentId = {
                                    ...metric,
                                    experiment_id: values.experimentId,
                                }
                                const response = await performQuery(queryWithExperimentId, undefined, refresh)

                                return {
                                    ...response,
                                    fakeInsightId: Math.random().toString(36).substring(2, 15),
                                }
                            } catch (error: any) {
                                const errorDetailMatch = error.detail.match(/\{.*\}/)
                                const errorDetail = errorDetailMatch ? JSON.parse(errorDetailMatch[0]) : error.detail

                                const currentErrors = [...(values.secondaryMetricsResultErrors || [])]
                                currentErrors[index] = {
                                    detail: errorDetail,
                                    statusCode: error.status,
                                    hasDiagnostics: !!errorDetailMatch,
                                }
                                actions.setSecondaryMetricsResultErrors(currentErrors)
                                return null
                            }
                        })
                    )) as (CachedExperimentTrendsQueryResponse | CachedExperimentFunnelsQueryResponse | null)[]
                },
            },
        ],
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
    })),
    selectors({
        props: [() => [(_, props) => props], (props) => props],
        dynamicFeatureFlagKey: [
            (s) => [s.experiment],
            (experiment: Experiment): string => {
                return experiment.name
                    .toLowerCase()
                    .replace(/[^A-Za-z0-9-_]+/g, '-')
                    .replace(/-+$/, '')
                    .replace(/^-+/, '')
            },
        ],
        experimentId: [
            () => [(_, props) => props.experimentId ?? 'new'],
            (experimentId): Experiment['id'] => experimentId,
        ],
        _getMetricType: [
            () => [],
            () =>
                (metric: ExperimentTrendsQuery | ExperimentFunnelsQuery): InsightType => {
                    return metric?.kind === NodeKind.ExperimentTrendsQuery ? InsightType.TRENDS : InsightType.FUNNELS
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
                    targetValues.includes(entity?.math as PropertyMathType)
                )[0]?.math

                return (userMathValue ?? propertyMathValue) as PropertyMathType | CountPerActorMathType | undefined
            },
        ],
        minimumDetectableEffect: [
            (s) => [s.experiment, s._getMetricType, s.conversionMetrics, s.trendResults],
            (newExperiment, _getMetricType, conversionMetrics, trendResults): number => {
                return (
                    newExperiment?.parameters?.minimum_detectable_effect ||
                    // :KLUDGE: extracted the method due to difficulties with logic tests
                    getMinimumDetectableEffect(
                        _getMetricType(newExperiment?.metrics[0]),
                        conversionMetrics,
                        trendResults
                    ) ||
                    0
                )
            },
        ],
        minimumSampleSizePerVariant: [
            (s) => [s.minimumDetectableEffect],
            (mde) => (conversionRate: number) => {
                // Using the rule of thumb: sampleSize = 16 * sigma^2 / (mde^2)
                // refer https://en.wikipedia.org/wiki/Sample_size_determination with default beta and alpha
                // The results are same as: https://www.evanmiller.org/ab-testing/sample-size.html
                // and also: https://marketing.dynamicyield.com/ab-test-duration-calculator/
                if (!mde) {
                    return 0
                }

                return Math.ceil((1600 * conversionRate * (1 - conversionRate / 100)) / (mde * mde))
            },
        ],
        isPrimaryMetricSignificant: [
            (s) => [s.metricResults],
            (metricResults: (CachedExperimentFunnelsQueryResponse | CachedExperimentTrendsQueryResponse | null)[]) =>
                (metricIndex: number = 0): boolean => {
                    return metricResults?.[metricIndex]?.significant || false
                },
        ],
        isSecondaryMetricSignificant: [
            (s) => [s.secondaryMetricResults],
            (
                    secondaryMetricResults: (
                        | CachedExperimentFunnelsQueryResponse
                        | CachedExperimentTrendsQueryResponse
                        | null
                    )[]
                ) =>
                (metricIndex: number = 0): boolean => {
                    return secondaryMetricResults?.[metricIndex]?.significant || false
                },
        ],
        significanceDetails: [
            (s) => [s.metricResults],
            (metricResults: (CachedExperimentFunnelsQueryResponse | CachedExperimentTrendsQueryResponse | null)[]) =>
                (metricIndex: number = 0): string => {
                    const results = metricResults?.[metricIndex]

                    if (results?.significance_code === ExperimentSignificanceCode.HighLoss) {
                        return `This is because the expected loss in conversion is greater than 1% (current value is ${(
                            (results as CachedExperimentFunnelsQueryResponse)?.expected_loss || 0
                        )?.toFixed(2)}%).`
                    }

                    if (results?.significance_code === ExperimentSignificanceCode.HighPValue) {
                        return `This is because the p value is greater than 0.05 (current value is ${
                            (results as CachedExperimentTrendsQueryResponse)?.p_value?.toFixed(3) || 1
                        }).`
                    }

                    if (results?.significance_code === ExperimentSignificanceCode.LowWinProbability) {
                        return 'This is because the win probability of all test variants combined is less than 90%.'
                    }

                    if (results?.significance_code === ExperimentSignificanceCode.NotEnoughExposure) {
                        return 'This is because we need at least 100 people per variant to declare significance.'
                    }

                    return ''
                },
        ],
        recommendedSampleSize: [
            (s) => [s.conversionMetrics, s.minimumSampleSizePerVariant, s.variants],
            (conversionMetrics, minimumSampleSizePerVariant, variants): number => {
                const conversionRate = conversionMetrics.totalRate * 100
                const sampleSizePerVariant = minimumSampleSizePerVariant(conversionRate)
                const sampleSize = sampleSizePerVariant * variants.length
                return sampleSize
            },
        ],
        recommendedRunningTime: [
            (s) => [
                s.experiment,
                s.variants,
                s._getMetricType,
                s.funnelResults,
                s.conversionMetrics,
                s.expectedRunningTime,
                s.trendResults,
                s.minimumSampleSizePerVariant,
                s.recommendedExposureForCountData,
            ],
            (
                experiment,
                variants,
                _getMetricType,
                funnelResults,
                conversionMetrics,
                expectedRunningTime,
                trendResults,
                minimumSampleSizePerVariant,
                recommendedExposureForCountData
            ): number => {
                if (_getMetricType(experiment.metrics[0]) === InsightType.FUNNELS) {
                    const currentDuration = dayjs().diff(dayjs(experiment?.start_date), 'hour')
                    const funnelEntrants = funnelResults?.[0]?.count

                    const conversionRate = conversionMetrics.totalRate * 100
                    const sampleSizePerVariant = minimumSampleSizePerVariant(conversionRate)
                    const funnelSampleSize = sampleSizePerVariant * variants.length
                    if (experiment?.start_date) {
                        return expectedRunningTime(funnelEntrants || 1, funnelSampleSize || 0, currentDuration)
                    }
                    return expectedRunningTime(funnelEntrants || 1, funnelSampleSize || 0)
                }

                const trendCount = trendResults[0]?.count
                const runningTime = recommendedExposureForCountData(trendCount)
                return runningTime
            },
        ],
        recommendedExposureForCountData: [
            (s) => [s.minimumDetectableEffect],
            (mde) =>
                (baseCountData: number): number => {
                    // http://www.columbia.edu/~cjd11/charles_dimaggio/DIRE/styled-4/code-12/
                    if (!mde) {
                        return 0
                    }

                    const minCountData = (baseCountData * mde) / 100
                    const lambda1 = baseCountData
                    const lambda2 = minCountData + baseCountData

                    // This is exposure in units of days
                    return parseFloat(
                        (
                            4 /
                            Math.pow(
                                Math.sqrt(lambda1 / EXPERIMENT_DEFAULT_DURATION) -
                                    Math.sqrt(lambda2 / EXPERIMENT_DEFAULT_DURATION),
                                2
                            )
                        ).toFixed(1)
                    )
                },
        ],
        expectedRunningTime: [
            () => [],
            () =>
                (entrants: number, sampleSize: number, duration: number = EXPERIMENT_DEFAULT_DURATION): number => {
                    // recommended people / (actual people / day) = expected days
                    return parseFloat((sampleSize / (entrants / duration)).toFixed(1))
                },
        ],
        conversionRateForVariant: [
            () => [],
            () =>
                (
                    metricResult:
                        | Partial<ExperimentResults['result']>
                        | CachedExperimentFunnelsQueryResponse
                        | CachedExperimentTrendsQueryResponse
                        | null,
                    variantKey: string
                ): number | null => {
                    if (!metricResult || !metricResult.insight) {
                        return null
                    }
                    const variantResults = (metricResult.insight as FunnelStep[][]).find(
                        (variantFunnel: FunnelStep[]) => {
                            const breakdownValue = variantFunnel[0]?.breakdown_value
                            return Array.isArray(breakdownValue) && breakdownValue[0] === variantKey
                        }
                    )

                    if (!variantResults) {
                        return null
                    }
                    return (variantResults[variantResults.length - 1].count / variantResults[0].count) * 100
                },
        ],
        credibleIntervalForVariant: [
            (s) => [s.experimentStatsVersion],
            (experimentStatsVersion) =>
                (
                    metricResult:
                        | Partial<ExperimentResults['result']>
                        | CachedExperimentTrendsQueryResponse
                        | CachedExperimentFunnelsQueryResponse
                        | null,
                    variantKey: string,
                    metricType: InsightType
                ): [number, number] | null => {
                    const credibleInterval = metricResult?.credible_intervals?.[variantKey]
                    if (!credibleInterval) {
                        return null
                    }

                    if (metricType === InsightType.FUNNELS) {
                        const controlVariant = (metricResult.variants as FunnelExperimentVariant[]).find(
                            ({ key }) => key === 'control'
                        ) as FunnelExperimentVariant
                        const controlConversionRate =
                            controlVariant.success_count / (controlVariant.success_count + controlVariant.failure_count)

                        if (!controlConversionRate) {
                            return null
                        }

                        // Calculate the percentage difference between the credible interval bounds of the variant and the control's conversion rate.
                        // This represents the range in which the true percentage change relative to the control is likely to fall.
                        const lowerBound = ((credibleInterval[0] - controlConversionRate) / controlConversionRate) * 100
                        const upperBound = ((credibleInterval[1] - controlConversionRate) / controlConversionRate) * 100
                        return [lowerBound, upperBound]
                    }

                    const controlVariant = (metricResult.variants as TrendExperimentVariant[]).find(
                        ({ key }) => key === 'control'
                    ) as TrendExperimentVariant
                    const variant = (metricResult.variants as TrendExperimentVariant[]).find(
                        ({ key }) => key === variantKey
                    ) as TrendExperimentVariant

                    const controlMean = controlVariant.count / controlVariant.absolute_exposure

                    const meanLowerBound =
                        experimentStatsVersion === 2
                            ? credibleInterval[0] / variant.absolute_exposure
                            : credibleInterval[0]
                    const meanUpperBound =
                        experimentStatsVersion === 2
                            ? credibleInterval[1] / variant.absolute_exposure
                            : credibleInterval[1]

                    // Calculate the percentage difference between the credible interval bounds of the variant and the control's mean.
                    // This represents the range in which the true percentage change relative to the control is likely to fall.
                    const lowerBound = ((meanLowerBound - controlMean) / controlMean) * 100
                    const upperBound = ((meanUpperBound - controlMean) / controlMean) * 100
                    return [lowerBound, upperBound]
                },
        ],
        getIndexForVariant: [
            (s) => [s.experiment, s._getMetricType],
            (experiment, _getMetricType) =>
                (
                    metricResult:
                        | Partial<ExperimentResults['result']>
                        | CachedExperimentTrendsQueryResponse
                        | CachedExperimentFunnelsQueryResponse
                        | null,
                    variant: string
                ): number | null => {
                    // Ensures we get the right index from results, so the UI can
                    // display the right colour for the variant
                    if (!metricResult || !metricResult.insight) {
                        return null
                    }

                    let index = -1
                    if (_getMetricType(experiment.metrics[0]) === InsightType.FUNNELS) {
                        // Funnel Insight is displayed in order of decreasing count
                        index = (Array.isArray(metricResult.insight) ? [...metricResult.insight] : [])
                            .sort((a, b) => {
                                const aCount = (a && Array.isArray(a) && a[0]?.count) || 0
                                const bCount = (b && Array.isArray(b) && b[0]?.count) || 0
                                return bCount - aCount
                            })
                            .findIndex((variantFunnel) => {
                                if (!Array.isArray(variantFunnel) || !variantFunnel[0]?.breakdown_value) {
                                    return false
                                }
                                const breakdownValue = variantFunnel[0].breakdown_value
                                return Array.isArray(breakdownValue) && breakdownValue[0] === variant
                            })
                    } else {
                        index = (metricResult.insight as TrendResult[]).findIndex(
                            (variantTrend: TrendResult) => variantTrend.breakdown_value === variant
                        )
                    }
                    const result = index === -1 ? null : index

                    if (result !== null && _getMetricType(experiment.metrics[0]) === InsightType.FUNNELS) {
                        return result + 1
                    }
                    return result
                },
        ],
        countDataForVariant: [
            (s) => [s.experimentMathAggregationForTrends],
            (experimentMathAggregationForTrends) =>
                (
                    metricResult:
                        | Partial<ExperimentResults['result']>
                        | CachedExperimentTrendsQueryResponse
                        | CachedExperimentFunnelsQueryResponse
                        | null,
                    variant: string,
                    type: 'primary' | 'secondary' = 'primary'
                ): number | null => {
                    const usingMathAggregationType = type === 'primary' ? experimentMathAggregationForTrends() : false
                    if (!metricResult || !metricResult.insight) {
                        return null
                    }
                    const variantResults = (metricResult.insight as TrendResult[]).find(
                        (variantTrend: TrendResult) => variantTrend.breakdown_value === variant
                    )
                    if (!variantResults) {
                        return null
                    }

                    let result = variantResults.count

                    if (usingMathAggregationType) {
                        // TODO: Aggregate end result appropriately for nth percentile
                        if (
                            [
                                CountPerActorMathType.Average,
                                CountPerActorMathType.Median,
                                PropertyMathType.Average,
                                PropertyMathType.Median,
                            ].includes(usingMathAggregationType)
                        ) {
                            result = variantResults.count / variantResults.data.length
                        } else if (
                            [CountPerActorMathType.Maximum, PropertyMathType.Maximum].includes(usingMathAggregationType)
                        ) {
                            result = Math.max(...variantResults.data)
                        } else if (
                            [CountPerActorMathType.Minimum, PropertyMathType.Minimum].includes(usingMathAggregationType)
                        ) {
                            result = Math.min(...variantResults.data)
                        }
                    }

                    return result
                },
        ],
        exposureCountDataForVariant: [
            () => [],
            () =>
                (
                    metricResult:
                        | Partial<ExperimentResults['result']>
                        | CachedExperimentTrendsQueryResponse
                        | CachedExperimentFunnelsQueryResponse
                        | null,
                    variant: string
                ): number | null => {
                    if (!metricResult || !metricResult.variants) {
                        return null
                    }
                    const variantResults = (metricResult.variants as TrendExperimentVariant[]).find(
                        (variantTrend: TrendExperimentVariant) => variantTrend.key === variant
                    )
                    if (!variantResults || !variantResults.absolute_exposure) {
                        return null
                    }

                    const result = variantResults.absolute_exposure

                    return result
                },
        ],
        getHighestProbabilityVariant: [
            () => [],
            () =>
                (
                    results:
                        | ExperimentResults['result']
                        | CachedExperimentTrendsQueryResponse
                        | CachedExperimentFunnelsQueryResponse
                        | null
                ) => {
                    if (results && results.probability) {
                        const maxValue = Math.max(...Object.values(results.probability))
                        return Object.keys(results.probability).find(
                            (key) => Math.abs(results.probability[key] - maxValue) < Number.EPSILON
                        )
                    }
                },
        ],
        tabularExperimentResults: [
            (s) => [s.experiment, s.metricResults, s._getMetricType],
            (
                    experiment,
                    metricResults: (
                        | CachedExperimentFunnelsQueryResponse
                        | CachedExperimentTrendsQueryResponse
                        | null
                    )[],
                    _getMetricType
                ) =>
                (metricIndex: number = 0): any[] => {
                    const tabularResults = []
                    const metricType = _getMetricType(experiment.metrics[metricIndex])
                    const result = metricResults?.[metricIndex]

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
        tabularSecondaryMetricResults: [
            (s) => [s.experiment, s.secondaryMetricResults, s.conversionRateForVariant, s.countDataForVariant],
            (
                experiment,
                secondaryMetricResults,
                conversionRateForVariant,
                countDataForVariant
            ): TabularSecondaryMetricResults[] => {
                if (!secondaryMetricResults) {
                    return []
                }

                const variantsWithResults: TabularSecondaryMetricResults[] = []
                experiment?.feature_flag?.filters?.multivariate?.variants?.forEach((variant) => {
                    const metricResults: SecondaryMetricResult[] = []
                    experiment?.secondary_metrics?.forEach((metric, idx) => {
                        let result
                        if (metric.filters.insight === InsightType.FUNNELS) {
                            result = conversionRateForVariant(secondaryMetricResults?.[idx], variant.key)
                        } else {
                            result = countDataForVariant(secondaryMetricResults?.[idx], variant.key, 'secondary')
                        }

                        metricResults.push({
                            insightType: metric.filters.insight || InsightType.TRENDS,
                            result: result || undefined,
                        })
                    })

                    variantsWithResults.push({
                        variant: variant.key,
                        results: metricResults,
                    })
                })
                return variantsWithResults
            },
        ],
        sortedWinProbabilities: [
            (s) => [s.metricResults, s.conversionRateForVariant],
            (
                    metricResults: (
                        | CachedExperimentFunnelsQueryResponse
                        | CachedExperimentTrendsQueryResponse
                        | null
                    )[],
                    conversionRateForVariant
                ) =>
                (metricIndex: number = 0) => {
                    const result = metricResults?.[metricIndex]

                    if (!result || !result.probability) {
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
            (s) => [s.experiment, s.metricResults, s._getMetricType],
            (
                    experiment,
                    metricResults: (
                        | CachedExperimentFunnelsQueryResponse
                        | CachedExperimentTrendsQueryResponse
                        | null
                    )[],
                    _getMetricType
                ) =>
                (metricIndex: number = 0): number => {
                    const result = metricResults?.[metricIndex]

                    if (_getMetricType(experiment.metrics[metricIndex]) !== InsightType.FUNNELS || !result?.insight) {
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
        hasGoalSet: [
            (s) => [s.experiment],
            (experiment): boolean => {
                return !!experiment.metrics[0]
            },
        ],
        experimentStatsVersion: [
            (s) => [s.experiment],
            (experiment: Experiment): number => {
                return experiment.stats_config?.version || 1
            },
        ],
    }),
    forms(({ actions }) => ({
        experiment: {
            options: { showErrorsOnTouch: true },
            defaults: { ...NEW_EXPERIMENT } as Experiment,
            errors: ({ name, feature_flag_key, parameters }) => ({
                name: !name && 'Please enter a name',
                feature_flag_key: validateFeatureFlagKey(feature_flag_key),
                parameters: {
                    feature_flag_variants: parameters.feature_flag_variants?.map(({ key }) => ({
                        key: !key.match?.(/^([A-z]|[a-z]|[0-9]|-|_)+$/)
                            ? 'Only letters, numbers, hyphens (-) & underscores (_) are allowed.'
                            : undefined,
                    })),
                },
            }),
            submit: () => actions.createExperiment(true),
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/experiments/:id': ({ id }, _, __, currentLocation, previousLocation) => {
            const didPathChange = currentLocation.initial || currentLocation.pathname !== previousLocation?.pathname

            actions.setEditExperiment(false)

            if (id && didPathChange) {
                const parsedId = id === 'new' ? 'new' : parseInt(id)
                if (parsedId === 'new') {
                    actions.resetExperiment()
                }
                if (parsedId !== 'new' && parsedId === values.experimentId) {
                    actions.loadExperiment()
                }
            }
        },
    })),
])

export function percentageDistribution(variantCount: number): number[] {
    const basePercentage = Math.floor(100 / variantCount)
    const percentages = new Array(variantCount).fill(basePercentage)
    let remaining = 100 - basePercentage * variantCount
    for (let i = 0; remaining > 0; i++, remaining--) {
        // try to equally distribute `remaining` across variants
        percentages[i] += 1
    }
    return percentages
}

export function getDefaultFilters(insightType: InsightType, aggregationGroupTypeIndex: number | undefined): FilterType {
    let newInsightFilters
    if (insightType === InsightType.TRENDS) {
        const groupAggregation =
            aggregationGroupTypeIndex !== undefined
                ? { math: 'unique_group', math_group_type_index: aggregationGroupTypeIndex }
                : {}

        newInsightFilters = cleanFilters({
            insight: InsightType.TRENDS,
            events: [{ ...getDefaultEvent(), ...groupAggregation }],
            date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
            date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
            display: ChartDisplayType.ActionsLineGraph,
            entity: EntityTypes.EVENTS,
            filter_test_accounts: true,
        } as TrendsFilterType)
    } else {
        newInsightFilters = cleanFilters({
            insight: InsightType.FUNNELS,
            events: [
                {
                    id: '$pageview',
                    name: '$pageview',
                    type: 'events',
                    order: 0,
                },
                {
                    id: '$pageview',
                    name: 'Pageview',
                    type: 'events',
                    order: 1,
                },
            ],
            funnel_viz_type: FunnelVizType.Steps,
            date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
            date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
            layout: FunnelLayout.horizontal,
            aggregation_group_type_index: aggregationGroupTypeIndex,
            funnel_window_interval: 14,
            funnel_window_interval_unit: FunnelConversionWindowTimeUnit.Day,
            filter_test_accounts: true,
        })
    }

    return newInsightFilters
}

export function getDefaultTrendsMetric(): ExperimentTrendsQuery {
    return {
        kind: NodeKind.ExperimentTrendsQuery,
        count_query: {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    name: '$pageview',
                    event: '$pageview',
                },
            ],
            interval: 'day',
            dateRange: {
                date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                explicitDate: true,
            },
            trendsFilter: {
                display: ChartDisplayType.ActionsLineGraph,
            },
            filterTestAccounts: true,
        },
    }
}

export function getDefaultFunnelsMetric(): ExperimentFunnelsQuery {
    return {
        kind: NodeKind.ExperimentFunnelsQuery,
        funnels_query: {
            kind: NodeKind.FunnelsQuery,
            filterTestAccounts: true,
            dateRange: {
                date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                explicitDate: true,
            },
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                },
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                },
            ],
            funnelsFilter: {
                funnelVizType: FunnelVizType.Steps,
                funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                funnelWindowInterval: 14,
                layout: FunnelLayout.horizontal,
            },
        },
    }
}
