import { ReactElement } from 'react'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import {
    Breadcrumb,
    Experiment,
    ExperimentResults,
    FilterType,
    FunnelVizType,
    InsightModel,
    InsightType,
    InsightShortId,
    MultivariateFlagVariant,
    TrendResult,
    FunnelStep,
    SecondaryExperimentMetric,
    AvailableFeature,
    SignificanceCode,
    SecondaryMetricResult,
} from '~/types'
import type { experimentLogicType } from './experimentLogicType'
import { router, urlToAction } from 'kea-router'
import { experimentsLogic } from './experimentsLogic'
import { FunnelLayout, INSTANTLY_AVAILABLE_PROPERTIES } from 'lib/constants'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { userLogic } from 'scenes/userLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { InfoCircleOutlined } from '@ant-design/icons'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { groupsModel } from '~/models/groupsModel'
import { lemonToast } from 'lib/components/lemonToast'
import { convertPropertyGroupToProperties, toParams } from 'lib/utils'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

const DEFAULT_DURATION = 14 // days

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
    created_at: '',
    created_by: null,
}

export interface ExperimentLogicProps {
    experimentId?: Experiment['id']
}

interface SecondaryMetricResult {
    insightType: InsightType
    result: number
}

export interface TabularSecondaryMetricResults {
    variant: string
    results?: SecondaryMetricResult[]
}

export const experimentLogic = kea<experimentLogicType>([
    props({} as ExperimentLogicProps),
    key((props) => props.experimentId || 'new'),
    path((key) => ['scenes', 'experiment', 'experimentLogic', key]),
    connect({
        values: [
            teamLogic,
            ['currentTeamId'],
            userLogic,
            ['hasAvailableFeature'],
            groupsModel,
            ['groupTypes', 'groupsTaxonomicTypes', 'aggregationLabel'],
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
        ],
    }),
    actions({
        setExperiment: (experiment: Partial<Experiment>) => ({ experiment }),
        createExperiment: (draft?: boolean, runningTime?: number, sampleSize?: number) => ({
            draft,
            runningTime,
            sampleSize,
        }),
        setExperimentInsightId: (shortId: InsightShortId) => ({ shortId }),
        createNewExperimentInsight: (filters?: Partial<FilterType>) => ({ filters }),
        setFilters: (filters: Partial<FilterType>) => ({ filters }),
        removeExperimentGroup: (idx: number) => ({ idx }),
        setEditExperiment: (editing: boolean) => ({ editing }),
        setSecondaryMetrics: (secondaryMetrics: SecondaryExperimentMetric[]) => ({ secondaryMetrics }),
        setExperimentResultCalculationError: (error: string) => ({ error }),
        setFlagImplementationWarning: (warning: boolean) => ({ warning }),
        setFlagAvailabilityWarning: (warning: boolean) => ({ warning }),
        setExposureAndSampleSize: (exposure: number, sampleSize: number) => ({ exposure, sampleSize }),
        updateExperimentGoal: (filters: Partial<FilterType>) => ({ filters }),
        launchExperiment: true,
        endExperiment: true,
        addExperimentGroup: true,
        archiveExperiment: true,
        resetRunningExperiment: true,
        checkFlagImplementationWarning: true,
        checkFlagAvailabilityWarning: true,
        openExperimentGoalModal: true,
        closeExperimentGoalModal: true,
    }),
    reducers({
        experiment: [
            { ...NEW_EXPERIMENT } as Experiment,
            {
                setExperiment: (state, { experiment }) => {
                    if (experiment.filters) {
                        const newFilters = { ...state.filters, ...experiment.filters }
                        return { ...state, ...experiment, filters: newFilters }
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
        experimentInsightId: [
            null as InsightShortId | null,
            {
                setExperimentInsightId: (_, { shortId }) => shortId,
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
                loadExperimentResults: () => false,
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
        flagAvailabilityWarning: [
            false as boolean,
            {
                setFlagAvailabilityWarning: (_, { warning }) => warning,
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
                        }
                    )
                    if (response?.id) {
                        actions.updateExperiments(response)
                        actions.setEditExperiment(false)
                        actions.setExperiment(response)
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
        createNewExperimentInsight: async ({ filters }) => {
            let newInsightFilters
            if (filters?.insight === InsightType.FUNNELS) {
                newInsightFilters = cleanFilters({
                    insight: InsightType.FUNNELS,
                    funnel_viz_type: FunnelVizType.Steps,
                    date_from: dayjs().subtract(DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    layout: FunnelLayout.horizontal,
                    ...filters,
                })
            } else {
                newInsightFilters = cleanFilters({
                    insight: InsightType.TRENDS,
                    date_from: dayjs().subtract(DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    ...filters,
                })
            }

            const newInsight = {
                name: ``,
                description: '',
                tags: [],
                filters: newInsightFilters,
                result: null,
            }

            const createdInsight: InsightModel = await api.create(
                `api/projects/${values.currentTeamId}/insights`,
                newInsight
            )
            actions.setExperimentInsightId(createdInsight.short_id)

            actions.setExperiment({ filters: { ...newInsight.filters } })
        },
        setFilters: ({ filters }) => {
            if (values.experimentInsightType === InsightType.FUNNELS) {
                funnelLogic.findMounted({ dashboardItemId: values.experimentInsightId })?.actions.setFilters(filters)
            } else {
                trendsLogic.findMounted({ dashboardItemId: values.experimentInsightId })?.actions.setFilters(filters)
            }
        },
        loadExperimentSuccess: async ({ experiment }) => {
            experiment && actions.reportExperimentViewed(experiment)
            if (!experiment?.start_date) {
                // loading a draft experiment
                actions.createNewExperimentInsight(experiment?.filters)
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
            actions.updateExperiment({ filters })
            actions.closeExperimentGoalModal()
        },
        closeExperimentGoalModal: () => {
            if (values.experimentChanged) {
                actions.loadExperiment()
            }
        },
        resetRunningExperiment: async () => {
            actions.updateExperiment({ start_date: null, end_date: null })
            values.experiment && actions.reportExperimentReset(values.experiment)
        },
        updateExperimentSuccess: async ({ experiment }) => {
            actions.updateExperiments(experiment)

            if (values.changingGoalMetric) {
                actions.loadExperimentResults()
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
            actions.checkFlagAvailabilityWarning()
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

                actions.checkFlagAvailabilityWarning()
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
            actions.checkFlagAvailabilityWarning()
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
        checkFlagAvailabilityWarning: async () => {
            if (values.experiment.filters?.properties) {
                const targetProperties = convertPropertyGroupToProperties(values.experiment.filters.properties) || []

                if (targetProperties.length > 0) {
                    const hasNonInstantProperty = !!targetProperties.find(
                        (property) =>
                            property.type === 'cohort' || !INSTANTLY_AVAILABLE_PROPERTIES.includes(property.key || '')
                    )
                    actions.setFlagAvailabilityWarning(hasNonInstantProperty)
                } else {
                    actions.setFlagAvailabilityWarning(false)
                }
            }
        },
        openExperimentGoalModal: async () => {
            actions.createNewExperimentInsight(values.experiment?.filters)
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
                            throw error
                        } else {
                            lemonToast.error(`Failed to load experiment ${props.experimentId}`)
                            throw new Error(`Failed to load experiment ${props.experimentId}`)
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
            null as ExperimentResults | null,
            {
                loadExperimentResults: async () => {
                    try {
                        const response = await api.get(
                            `api/projects/${values.currentTeamId}/experiments/${values.experimentId}/results`
                        )
                        return { ...response, itemID: Math.random().toString(36).substring(2, 15) }
                    } catch (error: any) {
                        actions.setExperimentResultCalculationError(error.detail)
                        return null
                    }
                },
            },
        ],
        secondaryMetricResults: [
            null as SecondaryMetricResult[] | null,
            {
                loadSecondaryMetricResults: async () => {
                    return await Promise.all(
                        (values.experiment?.secondary_metrics || []).map(async (_, index) => {
                            try {
                                const secResults = await api.get(
                                    `api/projects/${values.currentTeamId}/experiments/${values.experimentId}/secondary_results?id=${index}`
                                )
                                return secResults.result
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
        breadcrumbs: [
            (s) => [s.experiment, s.experimentId],
            (experiment, experimentId): Breadcrumb[] => [
                {
                    name: 'Experiments',
                    path: urls.experiments(),
                },
                {
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
        taxonomicGroupTypesForSelection: [
            (s) => [s.experiment, s.groupsTaxonomicTypes],
            (newexperiment, groupsTaxonomicTypes): TaxonomicFilterGroupType[] => {
                if (newexperiment?.filters?.aggregation_group_type_index != null && groupsTaxonomicTypes.length > 0) {
                    return [groupsTaxonomicTypes[newexperiment.filters.aggregation_group_type_index]]
                }

                return [TaxonomicFilterGroupType.PersonProperties, TaxonomicFilterGroupType.Cohorts]
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
                                <InfoCircleOutlined style={{ padding: '4px 2px' }} />
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
                                <InfoCircleOutlined style={{ padding: '4px 2px' }} />
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
            (s) => [s.experimentResults],
            (experimentResults) =>
                (variant: string): string => {
                    const errorResult = '--'
                    if (!experimentResults) {
                        return errorResult
                    }
                    const variantResults = (experimentResults?.insight as FunnelStep[][]).find(
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
            (s) => [s.experimentResults],
            (experimentResults) =>
                (variant: string, insightType: InsightType): number => {
                    let result: number
                    // Ensures we get the right index from results, so the UI can
                    // display the right colour for the variant
                    if (!experimentResults) {
                        result = 0
                    } else {
                        let index = -1
                        if (insightType === InsightType.FUNNELS) {
                            // Funnel Insight is displayed in order of decreasing count
                            index = ([...experimentResults?.insight] as FunnelStep[][])
                                .sort((a, b) => b[0]?.count - a[0]?.count)
                                .findIndex(
                                    (variantFunnel: FunnelStep[]) => variantFunnel[0]?.breakdown_value?.[0] === variant
                                )
                        } else {
                            index = (experimentResults?.insight as TrendResult[]).findIndex(
                                (variantTrend: TrendResult) => variantTrend.breakdown_value === variant
                            )
                        }
                        result = index === -1 ? 0 : index
                    }
                    if (insightType === InsightType.FUNNELS) {
                        result++
                    }
                    return result
                },
        ],
        countDataForVariant: [
            (s) => [s.experimentResults],
            (experimentResults) =>
                (variant: string): string => {
                    const errorResult = '--'
                    if (!experimentResults) {
                        return errorResult
                    }
                    const variantResults = (experimentResults?.insight as TrendResult[]).find(
                        (variantTrend: TrendResult) => variantTrend.breakdown_value === variant
                    )
                    if (!variantResults) {
                        return errorResult
                    }
                    return variantResults.count.toString()
                },
        ],
        highestProbabilityVariant: [
            (s) => [s.experimentResults],
            (experimentResults) => {
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
                            result: secondaryMetricResults?.[idx]?.[variant.key],
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
                feature_flag_key: !feature_flag_key
                    ? 'You have to enter a feature flag key.'
                    : !feature_flag_key.match?.(/^([A-z]|[a-z]|[0-9]|-|_)+$/)
                    ? 'Only letters, numbers, hyphens (-) & underscores (_) are allowed.'
                    : undefined,
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
            if (!values.hasAvailableFeature(AvailableFeature.EXPERIMENTATION)) {
                router.actions.push('/experiments')
                return
            }
            const didPathChange = currentLocation.initial || currentLocation.pathname !== previousLocation?.pathname

            actions.setEditExperiment(false)

            if (id && didPathChange) {
                const parsedId = id === 'new' ? 'new' : parseInt(id)
                if (parsedId === 'new') {
                    actions.createNewExperimentInsight()
                    actions.resetExperiment()
                }

                if (parsedId !== 'new' && parsedId === values.experimentId) {
                    actions.loadExperiment()
                }
            }
        },
    })),
    afterMount(({ props, actions }) => {
        const foundExperiment = experimentsLogic
            .findMounted()
            ?.values.experiments.find((experiment) => experiment.id === props.experimentId)
        if (foundExperiment) {
            actions.setExperiment(foundExperiment)
        } else if (props.experimentId !== 'new') {
            actions.loadExperiment()
        }
    }),
])

function percentageDistribution(variantCount: number): number[] {
    const percentageRounded = Math.round(100 / variantCount)
    const totalRounded = percentageRounded * variantCount
    const delta = totalRounded - 100
    const percentages = new Array(variantCount).fill(percentageRounded)
    percentages[variantCount - 1] = percentageRounded - delta
    return percentages
}
