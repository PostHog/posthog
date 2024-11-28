import { IconInfo } from '@posthog/icons'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { EXPERIMENT_DEFAULT_DURATION, FunnelLayout } from 'lib/constants'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { hasFormErrors, toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { ReactElement } from 'react'
import { validateFeatureFlagKey } from 'scenes/feature-flags/featureFlagLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { cleanFilters, getDefaultEvent } from 'scenes/insights/utils/cleanFilters'
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
    ExperimentTrendsQuery,
    NodeKind,
} from '~/queries/schema'
import {
    ActionFilter as ActionFilterType,
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
    PropertyMathType,
    SecondaryMetricResults,
    SignificanceCode,
    TrendExperimentVariant,
    TrendResult,
    TrendsFilterType,
} from '~/types'

import { MetricInsightId } from './constants'
import type { experimentLogicType } from './experimentLogicType'
import { experimentsLogic } from './experimentsLogic'
import { holdoutsLogic } from './holdoutsLogic'
import { getMinimumDetectableEffect, transformFiltersForWinningVariant } from './utils'

const NEW_EXPERIMENT: Experiment = {
    id: 'new',
    name: '',
    type: 'product',
    feature_flag_key: '',
    filters: {},
    metrics: [],
    metrics_secondary: [],
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

// :FLAG: CLEAN UP AFTER MIGRATION
export interface CachedSecondaryMetricExperimentFunnelsQueryResponse extends CachedExperimentFunnelsQueryResponse {
    filters?: {
        insight?: InsightType
    }
}

// :FLAG: CLEAN UP AFTER MIGRATION
export interface CachedSecondaryMetricExperimentTrendsQueryResponse extends CachedExperimentTrendsQueryResponse {
    filters?: {
        insight?: InsightType
    }
}

export const experimentLogic = kea<experimentLogicType>([
    props({} as ExperimentLogicProps),
    key((props) => props.experimentId || 'new'),
    path((key) => ['scenes', 'experiment', 'experimentLogic', key]),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
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
        ],
    })),
    actions({
        setExperimentMissing: true,
        setExperiment: (experiment: Partial<Experiment>) => ({ experiment }),
        createExperiment: (draft?: boolean) => ({ draft }),
        setExperimentType: (type?: string) => ({ type }),
        removeExperimentGroup: (idx: number) => ({ idx }),
        setEditExperiment: (editing: boolean) => ({ editing }),
        setExperimentResultCalculationError: (error: ExperimentResultCalculationError) => ({ error }),
        setFlagImplementationWarning: (warning: boolean) => ({ warning }),
        setExposureAndSampleSize: (exposure: number, sampleSize: number) => ({ exposure, sampleSize }),
        updateExperimentGoal: (filters: Partial<FilterType>) => ({ filters }),
        updateExperimentCollectionGoal: true,
        updateExperimentExposure: (filters: Partial<FilterType> | null) => ({ filters }),
        changeExperimentStartDate: (startDate: string) => ({ startDate }),
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
        }: {
            metricIdx: number
            name?: string
            series?: any[]
            filterTestAccounts?: boolean
        }) => ({ metricIdx, name, series, filterTestAccounts }),
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
            isSecondary = false,
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
                setTrendsExposureMetric: (state, { metricIdx, name, series, filterTestAccounts }) => {
                    const metrics = [...(state?.metrics || [])]
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
                        metrics,
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
        experimentResultCalculationError: [
            null as ExperimentResultCalculationError | null,
            {
                setExperimentResultCalculationError: (_, { error }) => error,
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
                        `api/projects/${values.currentTeamId}/experiments/${values.experimentId}`,
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
                    response = await api.create(`api/projects/${values.currentTeamId}/experiments`, {
                        ...values.experiment,
                        parameters: {
                            ...values.experiment?.parameters,
                            recommended_running_time: recommendedRunningTime,
                            recommended_sample_size: recommendedSampleSize,
                            minimum_detectable_effect: minimumDetectableEffect,
                        },
                        ...(!draft && { start_date: dayjs() }),
                    })
                    response && actions.reportExperimentCreated(response)
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
                actions.loadExperimentResults()
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
        endExperiment: async () => {
            const endDate = dayjs()
            actions.updateExperiment({ end_date: endDate.toISOString() })
            const duration = endDate.diff(values.experiment?.start_date, 'second')
            values.experiment &&
                actions.reportExperimentCompleted(values.experiment, endDate, duration, values.areResultsSignificant)
        },
        archiveExperiment: async () => {
            actions.updateExperiment({ archived: true })
            values.experiment && actions.reportExperimentArchived(values.experiment)
        },
        updateExperimentGoal: async ({ filters }) => {
            // Reset MDE to the recommended setting
            actions.setExperiment({
                parameters: {
                    ...values.experiment.parameters,
                    minimum_detectable_effect: undefined,
                },
            })

            const { recommendedRunningTime, recommendedSampleSize, minimumDetectableEffect } = values

            const filtersToUpdate = { ...filters }
            delete filtersToUpdate.properties

            actions.updateExperiment({
                filters: filtersToUpdate,
                metrics: values.experiment.metrics,
                parameters: {
                    ...values.experiment?.parameters,
                    recommended_running_time: recommendedRunningTime,
                    recommended_sample_size: recommendedSampleSize,
                    minimum_detectable_effect: minimumDetectableEffect,
                },
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
            actions.closeExperimentCollectionGoalModal()
        },
        updateExperimentExposure: async ({ filters }) => {
            actions.updateExperiment({
                metrics: values.experiment.metrics,
                parameters: {
                    custom_exposure_filter: filters ?? undefined,
                    feature_flag_variants: values.experiment?.parameters?.feature_flag_variants,
                },
            })
        },
        closeExperimentCollectionGoalModal: () => {
            if (values.experimentValuesChangedLocally) {
                actions.loadExperiment()
            }
        },
        resetRunningExperiment: async () => {
            actions.updateExperiment({ start_date: null, end_date: null, archived: false })
            values.experiment && actions.reportExperimentReset(values.experiment)

            actions.loadExperimentResultsSuccess(null)
            actions.loadSecondaryMetricResultsSuccess([])
        },
        updateExperimentSuccess: async ({ experiment }) => {
            actions.updateExperiments(experiment)
            actions.loadExperimentResults()
            actions.loadSecondaryMetricResults()
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
                const url = `/api/projects/${values.currentTeamId}/experiments/requires_flag_implementation?${toParams(
                    experiment.filters || {}
                )}`
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
                await api.update(`api/projects/${values.currentTeamId}/experiments/${values.experimentId}`, {
                    parameters: updatedParameters,
                })
                actions.setExperiment({
                    parameters: updatedParameters,
                })
            } catch (error) {
                lemonToast.error('Failed to update experiment variant images')
            }
        },
    })),
    loaders(({ actions, props, values }) => ({
        experiment: {
            loadExperiment: async () => {
                if (props.experimentId && props.experimentId !== 'new') {
                    try {
                        const response = await api.get(
                            `api/projects/${values.currentTeamId}/experiments/${props.experimentId}`
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
                    `api/projects/${values.currentTeamId}/experiments/${values.experimentId}`,
                    update
                )
                return response
            },
        },
        experimentResults: [
            null as
                | ExperimentResults['result']
                | CachedExperimentTrendsQueryResponse
                | CachedExperimentFunnelsQueryResponse
                | null,
            {
                loadExperimentResults: async (
                    refresh?: boolean
                ): Promise<
                    | ExperimentResults['result']
                    | CachedExperimentTrendsQueryResponse
                    | CachedExperimentFunnelsQueryResponse
                    | null
                > => {
                    try {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (values.featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            // Queries are shareable, so we need to set the experiment_id for the backend to correctly associate the query with the experiment
                            const queryWithExperimentId = {
                                ...values.experiment.metrics[0],
                                experiment_id: values.experimentId,
                            }

                            const response = await performQuery(queryWithExperimentId, undefined, refresh)

                            return {
                                ...response,
                                fakeInsightId: Math.random().toString(36).substring(2, 15),
                            } as unknown as CachedExperimentTrendsQueryResponse | CachedExperimentFunnelsQueryResponse
                        }

                        const refreshParam = refresh ? '?refresh=true' : ''
                        const response: ExperimentResults = await api.get(
                            `api/projects/${values.currentTeamId}/experiments/${values.experimentId}/results${refreshParam}`
                        )
                        return {
                            ...response.result,
                            fakeInsightId: Math.random().toString(36).substring(2, 15),
                            last_refresh: response.last_refresh,
                        }
                    } catch (error: any) {
                        let errorDetail = error.detail
                        // :HANDLE FLAG: CLEAN UP AFTER MIGRATION
                        if (values.featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            const errorDetailMatch = error.detail.match(/\{.*\}/)
                            errorDetail = errorDetailMatch[0]
                        }
                        actions.setExperimentResultCalculationError({ detail: errorDetail, statusCode: error.status })
                        if (error.status === 504) {
                            actions.reportExperimentResultsLoadingTimeout(values.experimentId)
                        }
                        return null
                    }
                },
            },
        ],
        secondaryMetricResults: [
            null as
                | SecondaryMetricResults[]
                | (CachedExperimentTrendsQueryResponse | CachedExperimentFunnelsQueryResponse)[]
                | null,
            {
                loadSecondaryMetricResults: async (
                    refresh?: boolean
                ): Promise<
                    | SecondaryMetricResults[]
                    | (CachedExperimentTrendsQueryResponse | CachedExperimentFunnelsQueryResponse)[]
                    | null
                > => {
                    if (values.featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                        return (await Promise.all(
                            values.experiment?.metrics_secondary.map(async (metric) => {
                                try {
                                    // Queries are shareable, so we need to set the experiment_id for the backend to correctly associate the query with the experiment
                                    const queryWithExperimentId = {
                                        ...metric,
                                        experiment_id: values.experimentId,
                                    }
                                    const response: ExperimentResults = await api.create(
                                        `api/projects/${values.currentTeamId}/query`,
                                        { query: queryWithExperimentId, refresh: 'lazy_async' }
                                    )

                                    return {
                                        ...response,
                                        fakeInsightId: Math.random().toString(36).substring(2, 15),
                                        last_refresh: response.last_refresh || '',
                                    }
                                } catch (error) {
                                    return {}
                                }
                            })
                        )) as unknown as (CachedExperimentTrendsQueryResponse | CachedExperimentFunnelsQueryResponse)[]
                    }

                    const refreshParam = refresh ? '&refresh=true' : ''

                    return await Promise.all(
                        (values.experiment?.secondary_metrics || []).map(async (_, index) => {
                            try {
                                const secResults = await api.get(
                                    `api/projects/${values.currentTeamId}/experiments/${values.experimentId}/secondary_results?id=${index}${refreshParam}`
                                )
                                // :TRICKY: Maintain backwards compatibility for cached responses, remove after cache period has expired
                                if (secResults && secResults.result && !secResults.result.hasOwnProperty('result')) {
                                    return {
                                        result: { ...secResults.result },
                                        fakeInsightId: Math.random().toString(36).substring(2, 15),
                                        last_refresh: secResults.last_refresh,
                                    }
                                }

                                return {
                                    ...secResults.result,
                                    fakeInsightId: Math.random().toString(36).substring(2, 15),
                                    last_refresh: secResults.last_refresh,
                                }
                            } catch (error) {
                                return {}
                            }
                        })
                    )
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
                        `api/projects/${values.currentTeamId}/feature_flags/${values.experiment.feature_flag?.id}`,
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
        getMetricType: [
            (s) => [s.experiment, s.featureFlags],
            (experiment, featureFlags) =>
                (metricIdx: number = 0) => {
                    if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                        const query = experiment?.metrics?.[metricIdx]
                        return query?.kind === NodeKind.ExperimentTrendsQuery ? InsightType.TRENDS : InsightType.FUNNELS
                    }

                    return experiment?.filters?.insight || InsightType.FUNNELS
                },
        ],
        getSecondaryMetricType: [
            (s) => [s.experiment, s.featureFlags],
            (experiment, featureFlags) =>
                (metricIdx: number = 0) => {
                    if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                        const query = experiment?.metrics_secondary?.[metricIdx]
                        return query?.kind === NodeKind.ExperimentTrendsQuery ? InsightType.TRENDS : InsightType.FUNNELS
                    }

                    return experiment?.secondary_metrics?.[metricIdx]?.filters?.insight || InsightType.FUNNELS
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
            (s) => [s.experiment, s.featureFlags],
            (experiment, featureFlags) => (): PropertyMathType | CountPerActorMathType | undefined => {
                let entities: { math?: string }[] = []

                if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                    const query = experiment?.metrics?.[0] as ExperimentTrendsQuery
                    if (!query) {
                        return undefined
                    }
                    entities = query.count_query?.series || []
                } else {
                    const filters = experiment?.filters
                    if (!filters) {
                        return undefined
                    }
                    entities = [
                        ...(filters?.events || []),
                        ...(filters?.actions || []),
                        ...(filters?.data_warehouse || []),
                    ] as ActionFilterType[]
                }

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
            (s) => [s.experiment, s.getMetricType, s.conversionMetrics, s.trendResults],
            (newExperiment, getMetricType, conversionMetrics, trendResults): number => {
                return (
                    newExperiment?.parameters?.minimum_detectable_effect ||
                    // :KLUDGE: extracted the method due to difficulties with logic tests
                    getMinimumDetectableEffect(getMetricType(0), conversionMetrics, trendResults) ||
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
        areResultsSignificant: [
            (s) => [s.experimentResults],
            (experimentResults): boolean => {
                return experimentResults?.significant || false
            },
        ],
        // TODO: remove with the old UI
        significanceBannerDetails: [
            (s) => [s.experimentResults],
            (experimentResults): string | ReactElement => {
                if (experimentResults?.significance_code === SignificanceCode.HighLoss) {
                    return (
                        <>
                            This is because the expected loss in conversion is greater than 1%
                            <Tooltip
                                placement="right"
                                title={
                                    <>Current value is {((experimentResults?.expected_loss || 0) * 100)?.toFixed(2)}%</>
                                }
                            >
                                <IconInfo className="ml-1 text-muted text-xl" />
                            </Tooltip>
                            .
                        </>
                    )
                }

                if (experimentResults?.significance_code === SignificanceCode.HighPValue) {
                    return (
                        <>
                            This is because the p value is greater than 0.05
                            <Tooltip
                                placement="right"
                                title={<>Current value is {experimentResults?.p_value?.toFixed(3) || 1}.</>}
                            >
                                <IconInfo className="ml-1 text-muted text-xl" />
                            </Tooltip>
                            .
                        </>
                    )
                }

                if (experimentResults?.significance_code === SignificanceCode.LowWinProbability) {
                    return 'This is because the win probability of all test variants combined is less than 90%.'
                }

                if (experimentResults?.significance_code === SignificanceCode.NotEnoughExposure) {
                    return 'This is because we need at least 100 people per variant to declare significance.'
                }

                return ''
            },
        ],
        significanceDetails: [
            (s) => [s.experimentResults],
            (experimentResults): string => {
                if (experimentResults?.significance_code === SignificanceCode.HighLoss) {
                    return `This is because the expected loss in conversion is greater than 1% (current value is ${(
                        (experimentResults?.expected_loss || 0) * 100
                    )?.toFixed(2)}%).`
                }

                if (experimentResults?.significance_code === SignificanceCode.HighPValue) {
                    return `This is because the p value is greater than 0.05 (current value is ${
                        experimentResults?.p_value?.toFixed(3) || 1
                    }).`
                }

                if (experimentResults?.significance_code === SignificanceCode.LowWinProbability) {
                    return 'This is because the win probability of all test variants combined is less than 90%.'
                }

                if (experimentResults?.significance_code === SignificanceCode.NotEnoughExposure) {
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
                s.getMetricType,
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
                getMetricType,
                funnelResults,
                conversionMetrics,
                expectedRunningTime,
                trendResults,
                minimumSampleSizePerVariant,
                recommendedExposureForCountData
            ): number => {
                if (getMetricType(0) === InsightType.FUNNELS) {
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
                    experimentResults:
                        | Partial<ExperimentResults['result']>
                        | CachedExperimentFunnelsQueryResponse
                        | CachedExperimentTrendsQueryResponse
                        | null,
                    variantKey: string
                ): number | null => {
                    if (!experimentResults || !experimentResults.insight) {
                        return null
                    }
                    const variantResults = (experimentResults.insight as FunnelStep[][]).find(
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
            () => [],
            () =>
                (
                    experimentResults:
                        | Partial<ExperimentResults['result']>
                        | CachedSecondaryMetricExperimentFunnelsQueryResponse
                        | CachedSecondaryMetricExperimentTrendsQueryResponse
                        | null,
                    variantKey: string,
                    metricType: InsightType
                ): [number, number] | null => {
                    const credibleInterval = experimentResults?.credible_intervals?.[variantKey]
                    if (!credibleInterval) {
                        return null
                    }

                    if (metricType === InsightType.FUNNELS) {
                        const controlVariant = (experimentResults.variants as FunnelExperimentVariant[]).find(
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

                    const controlVariant = (experimentResults.variants as TrendExperimentVariant[]).find(
                        ({ key }) => key === 'control'
                    ) as TrendExperimentVariant

                    const controlMean = controlVariant.count / controlVariant.absolute_exposure

                    // Calculate the percentage difference between the credible interval bounds of the variant and the control's mean.
                    // This represents the range in which the true percentage change relative to the control is likely to fall.
                    const lowerBound = ((credibleInterval[0] - controlMean) / controlMean) * 100
                    const upperBound = ((credibleInterval[1] - controlMean) / controlMean) * 100
                    return [lowerBound, upperBound]
                },
        ],
        getIndexForVariant: [
            (s) => [s.getMetricType],
            (getMetricType) =>
                (
                    experimentResults:
                        | Partial<ExperimentResults['result']>
                        | CachedExperimentTrendsQueryResponse
                        | CachedExperimentFunnelsQueryResponse
                        | null,
                    variant: string
                ): number | null => {
                    // Ensures we get the right index from results, so the UI can
                    // display the right colour for the variant
                    if (!experimentResults || !experimentResults.insight) {
                        return null
                    }

                    let index = -1
                    if (getMetricType(0) === InsightType.FUNNELS) {
                        // Funnel Insight is displayed in order of decreasing count
                        index = (Array.isArray(experimentResults.insight) ? [...experimentResults.insight] : [])
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
                        index = (experimentResults.insight as TrendResult[]).findIndex(
                            (variantTrend: TrendResult) => variantTrend.breakdown_value === variant
                        )
                    }
                    const result = index === -1 ? null : index

                    if (result !== null && getMetricType(0) === InsightType.FUNNELS) {
                        return result + 1
                    }
                    return result
                },
        ],
        countDataForVariant: [
            (s) => [s.experimentMathAggregationForTrends],
            (experimentMathAggregationForTrends) =>
                (
                    experimentResults:
                        | Partial<ExperimentResults['result']>
                        | CachedExperimentTrendsQueryResponse
                        | CachedExperimentFunnelsQueryResponse
                        | null,
                    variant: string,
                    type: 'primary' | 'secondary' = 'primary'
                ): number | null => {
                    const usingMathAggregationType = type === 'primary' ? experimentMathAggregationForTrends() : false
                    if (!experimentResults || !experimentResults.insight) {
                        return null
                    }
                    const variantResults = (experimentResults.insight as TrendResult[]).find(
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
                    experimentResults:
                        | Partial<ExperimentResults['result']>
                        | CachedExperimentTrendsQueryResponse
                        | CachedExperimentFunnelsQueryResponse
                        | null,
                    variant: string
                ): number | null => {
                    if (!experimentResults || !experimentResults.variants) {
                        return null
                    }
                    const variantResults = (experimentResults.variants as TrendExperimentVariant[]).find(
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
        sortedExperimentResultVariants: [
            (s) => [s.experimentResults, s.experiment],
            (experimentResults, experiment): string[] => {
                if (experimentResults) {
                    const sortedResults = Object.keys(experimentResults.probability).sort(
                        (a, b) => experimentResults.probability[b] - experimentResults.probability[a]
                    )

                    experiment?.parameters?.feature_flag_variants?.forEach((variant) => {
                        if (!sortedResults.includes(variant.key)) {
                            sortedResults.push(variant.key)
                        }
                    })
                    return sortedResults
                }
                return []
            },
        ],
        tabularExperimentResults: [
            (s) => [s.experiment, s.experimentResults, s.getMetricType],
            (experiment, experimentResults, getMetricType): any => {
                const tabularResults = []
                const metricType = getMetricType(0)

                if (experimentResults) {
                    for (const variantObj of experimentResults.variants) {
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
                experiment?.parameters?.feature_flag_variants?.forEach((variant) => {
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
            (s) => [s.experimentResults, s.conversionRateForVariant],
            (
                experimentResults,
                conversionRateForVariant
            ): { key: string; winProbability: number; conversionRate: number | null }[] => {
                if (!experimentResults) {
                    return []
                }

                return Object.keys(experimentResults.probability)
                    .map((key) => ({
                        key,
                        winProbability: experimentResults.probability[key],
                        conversionRate: conversionRateForVariant(experimentResults, key),
                    }))
                    .sort((a, b) => b.winProbability - a.winProbability)
            },
        ],
        funnelResultsPersonsTotal: [
            (s) => [s.experimentResults, s.getMetricType],
            (experimentResults, getMetricType): number => {
                if (getMetricType(0) !== InsightType.FUNNELS || !experimentResults?.insight) {
                    return 0
                }

                let sum = 0
                experimentResults.insight.forEach((variantResult) => {
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
            (s) => [s.experiment, s.featureFlags],
            (experiment, featureFlags): boolean => {
                // :FLAG: CLEAN UP AFTER MIGRATION
                if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                    return !!experiment.metrics[0]
                }

                const filters = experiment?.filters
                return !!(
                    (filters?.actions && filters.actions.length > 0) ||
                    (filters?.events && filters.events.length > 0) ||
                    (filters?.data_warehouse && filters.data_warehouse.length > 0)
                )
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

function percentageDistribution(variantCount: number): number[] {
    const percentageRounded = Math.round(100 / variantCount)
    const totalRounded = percentageRounded * variantCount
    const delta = totalRounded - 100
    const percentages = new Array(variantCount).fill(percentageRounded)
    percentages[variantCount - 1] = percentageRounded - delta
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
