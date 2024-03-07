import { IconInfo } from '@posthog/icons'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { ReactElement } from 'react'
import { validateFeatureFlagKey } from 'scenes/feature-flags/featureFlagLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { cleanFilters, getDefaultEvent } from 'scenes/insights/utils/cleanFilters'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { InsightVizNode } from '~/queries/schema'
import {
    ActionFilter as ActionFilterType,
    Breadcrumb,
    CountPerActorMathType,
    Experiment,
    ExperimentResults,
    FilterType,
    FunnelStep,
    FunnelVizType,
    InsightType,
    MultivariateFlagVariant,
    PropertyMathType,
    SecondaryExperimentMetric,
    SecondaryMetricResults,
    SignificanceCode,
    TrendExperimentVariant,
    TrendResult,
} from '~/types'

import { EXPERIMENT_EXPOSURE_INSIGHT_ID, EXPERIMENT_INSIGHT_ID } from './constants'
import type { experimentLogicType } from './experimentLogicType'
import { experimentsLogic } from './experimentsLogic'

export const DEFAULT_DURATION = 14 // days

const NEW_EXPERIMENT: Experiment = {
    id: 'new',
    name: '',
    feature_flag_key: '',
    filters: {},
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
            ],
            insightDataLogic({ dashboardItemId: EXPERIMENT_INSIGHT_ID }),
            ['setQuery'],
            insightVizDataLogic({ dashboardItemId: EXPERIMENT_INSIGHT_ID }),
            ['updateQuerySource'],
            insightDataLogic({ dashboardItemId: EXPERIMENT_EXPOSURE_INSIGHT_ID }),
            ['setQuery as setExposureQuery'],
            insightVizDataLogic({ dashboardItemId: EXPERIMENT_EXPOSURE_INSIGHT_ID }),
            ['updateQuerySource as updateExposureQuerySource'],
        ],
    })),
    actions({
        setExperimentMissing: true,
        setExperiment: (experiment: Partial<Experiment>) => ({ experiment }),
        createExperiment: (draft?: boolean, runningTime?: number, sampleSize?: number) => ({
            draft,
            runningTime,
            sampleSize,
        }),
        setNewExperimentInsight: (filters?: Partial<FilterType>) => ({ filters }),
        setExperimentExposureInsight: (filters?: Partial<FilterType>) => ({ filters }),
        removeExperimentGroup: (idx: number) => ({ idx }),
        setEditExperiment: (editing: boolean) => ({ editing }),
        setExperimentResultCalculationError: (error: string) => ({ error }),
        setFlagImplementationWarning: (warning: boolean) => ({ warning }),
        setExposureAndSampleSize: (exposure: number, sampleSize: number) => ({ exposure, sampleSize }),
        updateExperimentGoal: (filters: Partial<FilterType>) => ({ filters }),
        updateExperimentExposure: (filters: Partial<FilterType> | null) => ({ filters }),
        updateExperimentSecondaryMetrics: (metrics: SecondaryExperimentMetric[]) => ({ metrics }),
        launchExperiment: true,
        endExperiment: true,
        addExperimentGroup: true,
        archiveExperiment: true,
        resetRunningExperiment: true,
        checkFlagImplementationWarning: true,
        openExperimentGoalModal: true,
        closeExperimentGoalModal: true,
        openExperimentExposureModal: true,
        closeExperimentExposureModal: true,
    }),
    reducers({
        experiment: [
            { ...NEW_EXPERIMENT } as Experiment,
            {
                setExperiment: (state, { experiment }) => {
                    if (experiment.filters) {
                        return { ...state, ...experiment, filters: experiment.filters }
                    }

                    // assuming setExperiment isn't called with new filters & parameters at the same time
                    if (experiment.parameters) {
                        const newParameters = { ...state?.parameters, ...experiment.parameters }
                        return { ...state, ...experiment, parameters: newParameters }
                    }
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
        changingGoalMetric: [
            false,
            {
                updateExperimentGoal: () => true,
                updateExperimentExposure: () => true,
                loadExperimentResults: () => false,
            },
        ],
        changingSecondaryMetrics: [
            false,
            {
                updateExperimentSecondaryMetrics: () => true,
                loadSecondaryMetricResults: () => false,
            },
        ],
        experimentResultCalculationError: [
            null as string | null,
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
        exposureAndSampleSize: [
            { exposure: 0, sampleSize: 0 } as { exposure: number; sampleSize: number },
            {
                setExposureAndSampleSize: (_, { exposure, sampleSize }) => ({ exposure, sampleSize }),
            },
        ],
        isExperimentGoalModalOpen: [
            false,
            {
                openExperimentGoalModal: () => true,
                closeExperimentGoalModal: () => false,
            },
        ],
        isExperimentExposureModalOpen: [
            false,
            {
                openExperimentExposureModal: () => true,
                closeExperimentExposureModal: () => false,
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
    }),
    listeners(({ values, actions }) => ({
        createExperiment: async ({ draft, runningTime, sampleSize }) => {
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
                                recommended_running_time: runningTime,
                                recommended_sample_size: sampleSize,
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
                            recommended_running_time: runningTime,
                            recommended_sample_size: sampleSize,
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
        setNewExperimentInsight: async ({ filters }) => {
            let newInsightFilters
            const aggregationGroupTypeIndex = values.experiment.parameters?.aggregation_group_type_index
            if (filters?.insight === InsightType.FUNNELS) {
                newInsightFilters = cleanFilters({
                    insight: InsightType.FUNNELS,
                    funnel_viz_type: FunnelVizType.Steps,
                    date_from: dayjs().subtract(DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    layout: FunnelLayout.horizontal,
                    aggregation_group_type_index: aggregationGroupTypeIndex,
                    ...filters,
                })
            } else {
                const groupAggregation =
                    aggregationGroupTypeIndex !== undefined
                        ? { math: 'unique_group', math_group_type_index: aggregationGroupTypeIndex }
                        : {}
                const eventAddition =
                    filters?.actions || filters?.events
                        ? {}
                        : { events: [{ ...getDefaultEvent(), ...groupAggregation }] }
                newInsightFilters = cleanFilters({
                    insight: InsightType.TRENDS,
                    date_from: dayjs().subtract(DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    ...eventAddition,
                    ...filters,
                })
            }

            actions.updateQuerySource(filtersToQueryNode(newInsightFilters))
        },
        // sync form value `filters` with query
        setQuery: ({ query }) => {
            actions.setExperiment({ filters: queryNodeToFilter((query as InsightVizNode).source) })
        },
        setExperimentExposureInsight: async ({ filters }) => {
            const newInsightFilters = cleanFilters({
                insight: InsightType.TRENDS,
                date_from: dayjs().subtract(DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                ...filters,
            })

            actions.updateExposureQuerySource(filtersToQueryNode(newInsightFilters))
        },
        // sync form value `filters` with query
        setExposureQuery: ({ query }) => {
            actions.setExperiment({
                parameters: {
                    custom_exposure_filter: queryNodeToFilter((query as InsightVizNode).source),
                    feature_flag_variants: values.experiment?.parameters?.feature_flag_variants,
                },
            })
        },
        loadExperimentSuccess: async ({ experiment }) => {
            experiment && actions.reportExperimentViewed(experiment)
            if (!experiment?.start_date) {
                // loading a draft experiment
                actions.setNewExperimentInsight(experiment?.filters)
            } else {
                actions.loadExperimentResults()
                actions.loadSecondaryMetricResults()
            }
        },
        launchExperiment: async () => {
            const startDate = dayjs()
            actions.updateExperiment({ start_date: startDate.toISOString() })
            values.experiment && eventUsageLogic.actions.reportExperimentLaunched(values.experiment, startDate)
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
            // We never want to update global properties in the experiment
            const filtersToUpdate = { ...filters }
            delete filtersToUpdate.properties
            actions.updateExperiment({ filters: filtersToUpdate })
            actions.closeExperimentGoalModal()
        },
        updateExperimentExposure: async ({ filters }) => {
            actions.updateExperiment({
                parameters: {
                    custom_exposure_filter: filters ?? undefined,
                    feature_flag_variants: values.experiment?.parameters?.feature_flag_variants,
                },
            })
            actions.closeExperimentExposureModal()
        },
        updateExperimentSecondaryMetrics: async ({ metrics }) => {
            actions.updateExperiment({ secondary_metrics: metrics })
        },
        closeExperimentGoalModal: () => {
            if (values.experimentValuesChangedLocally) {
                actions.loadExperiment()
            }
        },
        closeExperimentExposureModal: () => {
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

            if (values.changingGoalMetric) {
                actions.loadExperimentResults()
            }

            if (values.changingSecondaryMetrics) {
                actions.loadSecondaryMetricResults()
            }
        },
        setExperiment: async ({ experiment }) => {
            const experimentEntitiesChanged =
                (experiment.filters?.events && experiment.filters.events.length > 0) ||
                (experiment.filters?.actions && experiment.filters.actions.length > 0)

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
                    (value?.events && value.events.length > 0) || (value?.actions && value.actions.length > 0)

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
                (experiment.filters?.actions && experiment.filters.actions.length > 0)

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
                (experiment.filters?.actions && experiment.filters.actions.length > 0)

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
        openExperimentGoalModal: async () => {
            actions.setNewExperimentInsight(values.experiment?.filters)
        },
        openExperimentExposureModal: async () => {
            actions.setExperimentExposureInsight(values.experiment?.parameters?.custom_exposure_filter)
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
            null as ExperimentResults['result'] | null,
            {
                loadExperimentResults: async (refresh?: boolean) => {
                    try {
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
                        actions.setExperimentResultCalculationError(error.detail)
                        return null
                    }
                },
            },
        ],
        secondaryMetricResults: [
            null as SecondaryMetricResults[] | null,
            {
                loadSecondaryMetricResults: async (refresh?: boolean) => {
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
    })),
    selectors({
        props: [() => [(_, props) => props], (props) => props],
        experimentId: [
            () => [(_, props) => props.experimentId ?? 'new'],
            (experimentId): Experiment['id'] => experimentId,
        ],
        experimentInsightType: [
            (s) => [s.experiment],
            (experiment): InsightType => {
                return experiment?.filters?.insight || InsightType.TRENDS
            },
        ],
        isExperimentRunning: [
            (s) => [s.experiment],
            (experiment): boolean => {
                return !!experiment?.start_date
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
                    name: experiment?.name || 'New',
                    path: urls.experiment(experimentId || 'new'),
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
            () => [],
            () =>
                (filters?: FilterType): PropertyMathType | CountPerActorMathType | undefined => {
                    // Find out if we're using count per actor math aggregates averages per user
                    const userMathValue = (
                        [...(filters?.events || []), ...(filters?.actions || [])] as ActionFilterType[]
                    ).filter((entity) =>
                        Object.values(CountPerActorMathType).includes(entity?.math as CountPerActorMathType)
                    )[0]?.math

                    // alternatively, if we're using property math
                    // remove 'sum' property math from the list of math types
                    // since we can handle that as a regular case
                    const targetValues = Object.values(PropertyMathType).filter(
                        (value) => value !== PropertyMathType.Sum
                    )
                    // sync with the backend at https://github.com/PostHog/posthog/blob/master/ee/clickhouse/queries/experiments/trend_experiment_result.py#L44
                    // the function uses_math_aggregation_by_user_or_property_value

                    const propertyMathValue = (
                        [...(filters?.events || []), ...(filters?.actions || [])] as ActionFilterType[]
                    ).filter((entity) => targetValues.includes(entity?.math as PropertyMathType))[0]?.math

                    return (userMathValue ?? propertyMathValue) as PropertyMathType | CountPerActorMathType | undefined
                },
        ],
        minimumDetectableChange: [
            (s) => [s.experiment],
            (newexperiment): number => {
                return newexperiment?.parameters?.minimum_detectable_effect || 5
            },
        ],
        minimumSampleSizePerVariant: [
            (s) => [s.minimumDetectableChange],
            (mde) => (conversionRate: number) => {
                // Using the rule of thumb: sampleSize = 16 * sigma^2 / (mde^2)
                // refer https://en.wikipedia.org/wiki/Sample_size_determination with default beta and alpha
                // The results are same as: https://www.evanmiller.org/ab-testing/sample-size.html
                // and also: https://marketing.dynamicyield.com/ab-test-duration-calculator/
                return Math.ceil((1600 * conversionRate * (1 - conversionRate / 100)) / (mde * mde))
            },
        ],
        areResultsSignificant: [
            (s) => [s.experimentResults],
            (experimentResults): boolean => {
                return experimentResults?.significant || false
            },
        ],
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
        recommendedExposureForCountData: [
            (s) => [s.minimumDetectableChange],
            (mde) =>
                (baseCountData: number): number => {
                    // http://www.columbia.edu/~cjd11/charles_dimaggio/DIRE/styled-4/code-12/
                    const minCountData = (baseCountData * mde) / 100
                    const lambda1 = baseCountData
                    const lambda2 = minCountData + baseCountData

                    // This is exposure in units of days
                    return parseFloat(
                        (
                            4 /
                            Math.pow(Math.sqrt(lambda1 / DEFAULT_DURATION) - Math.sqrt(lambda2 / DEFAULT_DURATION), 2)
                        ).toFixed(1)
                    )
                },
        ],
        expectedRunningTime: [
            () => [],
            () =>
                (entrants: number, sampleSize: number, duration: number = DEFAULT_DURATION): number => {
                    // recommended people / (actual people / day) = expected days
                    return parseFloat((sampleSize / (entrants / duration)).toFixed(1))
                },
        ],
        conversionRateForVariant: [
            () => [],
            () =>
                (experimentResults: Partial<ExperimentResults['result']> | null, variant: string): string => {
                    const errorResult = '--'
                    if (!experimentResults || !experimentResults.insight) {
                        return errorResult
                    }
                    const variantResults = (experimentResults.insight as FunnelStep[][]).find(
                        (variantFunnel: FunnelStep[]) => variantFunnel[0]?.breakdown_value?.[0] === variant
                    )
                    if (!variantResults) {
                        return errorResult
                    }
                    return ((variantResults[variantResults.length - 1].count / variantResults[0].count) * 100).toFixed(
                        1
                    )
                },
        ],
        getIndexForVariant: [
            () => [],
            () =>
                (experimentResults: Partial<ExperimentResults['result']> | null, variant: string): number | null => {
                    // TODO: Would be nice for every secondary metric to have the same colour for variants
                    const insightType = experimentResults?.filters?.insight
                    let result: number | null = null
                    // Ensures we get the right index from results, so the UI can
                    // display the right colour for the variant
                    if (!experimentResults || !experimentResults.insight) {
                        return null
                    } else {
                        let index = -1
                        if (insightType === InsightType.FUNNELS) {
                            // Funnel Insight is displayed in order of decreasing count
                            index = ([...experimentResults.insight] as FunnelStep[][])
                                .sort((a, b) => b[0]?.count - a[0]?.count)
                                .findIndex(
                                    (variantFunnel: FunnelStep[]) => variantFunnel[0]?.breakdown_value?.[0] === variant
                                )
                        } else {
                            index = (experimentResults.insight as TrendResult[]).findIndex(
                                (variantTrend: TrendResult) => variantTrend.breakdown_value === variant
                            )
                        }
                        result = index === -1 ? null : index
                    }
                    if (result !== null && insightType === InsightType.FUNNELS) {
                        result++
                    }
                    return result
                },
        ],
        countDataForVariant: [
            (s) => [s.experimentMathAggregationForTrends],
            (experimentMathAggregationForTrends) =>
                (experimentResults: Partial<ExperimentResults['result']> | null, variant: string): string => {
                    const usingMathAggregationType = experimentMathAggregationForTrends(
                        experimentResults?.filters || {}
                    )
                    const errorResult = '--'
                    if (!experimentResults || !experimentResults.insight) {
                        return errorResult
                    }
                    const variantResults = (experimentResults.insight as TrendResult[]).find(
                        (variantTrend: TrendResult) => variantTrend.breakdown_value === variant
                    )
                    if (!variantResults) {
                        return errorResult
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

                    if (result % 1 !== 0) {
                        // not an integer, so limit to 2 digits post decimal
                        return result.toFixed(2)
                    } else {
                        return result.toString()
                    }
                },
        ],
        exposureCountDataForVariant: [
            () => [],
            () =>
                (experimentResults: Partial<ExperimentResults['result']> | null, variant: string): string => {
                    const errorResult = '--'
                    if (!experimentResults || !experimentResults.variants) {
                        return errorResult
                    }
                    const variantResults = (experimentResults.variants as TrendExperimentVariant[]).find(
                        (variantTrend: TrendExperimentVariant) => variantTrend.key === variant
                    )
                    if (!variantResults || !variantResults.absolute_exposure) {
                        return errorResult
                    }

                    const result = variantResults.absolute_exposure

                    if (result % 1 !== 0) {
                        // not an integer, so limit to 2 digits post decimal
                        return result.toFixed(2)
                    } else {
                        return result.toString()
                    }
                },
        ],
        highestProbabilityVariant: [
            (s) => [s.experimentResults],
            (experimentResults: ExperimentResults['result']) => {
                if (experimentResults) {
                    const maxValue = Math.max(...Object.values(experimentResults.probability))
                    return Object.keys(experimentResults.probability).find(
                        (key) => Math.abs(experimentResults.probability[key] - maxValue) < Number.EPSILON
                    )
                }
            },
        ],
        areTrendResultsConfusing: [
            (s) => [s.experimentResults, s.highestProbabilityVariant],
            (experimentResults, highestProbabilityVariant): boolean => {
                // Results are confusing when the top variant has a lower
                // absolute count than other variants. This happens because
                // exposure is invisible to the user
                if (!experimentResults) {
                    return false
                }
                // find variant with highest count
                const variantResults: TrendResult = (experimentResults?.insight as TrendResult[]).reduce(
                    (bestVariant, currentVariant) =>
                        currentVariant.count > bestVariant.count ? currentVariant : bestVariant,
                    { count: 0, breakdown_value: '' } as TrendResult
                )
                if (!variantResults.count) {
                    return false
                }

                return variantResults.breakdown_value !== highestProbabilityVariant
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
        tabularSecondaryMetricResults: [
            (s) => [s.experiment, s.secondaryMetricResults],
            (experiment, secondaryMetricResults): TabularSecondaryMetricResults[] => {
                const variantsWithResults: TabularSecondaryMetricResults[] = []
                experiment?.parameters?.feature_flag_variants?.forEach((variant) => {
                    const metricResults: SecondaryMetricResult[] = []
                    experiment?.secondary_metrics?.forEach((metric, idx) => {
                        metricResults.push({
                            insightType: metric.filters.insight || InsightType.TRENDS,
                            result: secondaryMetricResults?.[idx]?.result?.[variant.key],
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
    }),
    forms(({ actions, values }) => ({
        experiment: {
            defaults: { ...NEW_EXPERIMENT } as Experiment,
            errors: ({ name, feature_flag_key, parameters }) => ({
                name: !name && 'You have to enter a name.',
                feature_flag_key: validateFeatureFlagKey(feature_flag_key),
                parameters: {
                    feature_flag_variants: parameters.feature_flag_variants?.map(({ key }) => ({
                        key: !key.match?.(/^([A-z]|[a-z]|[0-9]|-|_)+$/)
                            ? 'Only letters, numbers, hyphens (-) & underscores (_) are allowed.'
                            : undefined,
                    })),
                },
            }),
            submit: () => {
                const { exposure, sampleSize } = values.exposureAndSampleSize
                actions.createExperiment(true, exposure, sampleSize)
            },
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
                    actions.setNewExperimentInsight()
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
