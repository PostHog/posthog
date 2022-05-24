import { kea } from 'kea'
import React, { ReactElement } from 'react'
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
    ChartDisplayType,
    TrendResult,
    FunnelStep,
    SecondaryExperimentMetric,
    AvailableFeature,
    SignificanceCode,
    SecondaryMetricResult,
} from '~/types'
import type { experimentLogicType } from './experimentLogicType'
import { router } from 'kea-router'
import { experimentsLogic } from './experimentsLogic'
import { FunnelLayout } from 'lib/constants'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { userLogic } from 'scenes/userLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { InfoCircleOutlined } from '@ant-design/icons'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { groupsModel } from '~/models/groupsModel'
import { lemonToast } from 'lib/components/lemonToast'

const DEFAULT_DURATION = 14 // days

export interface ExperimentLogicProps {
    experimentId?: Experiment['id']
}

export const experimentLogic = kea<experimentLogicType>({
    props: {} as ExperimentLogicProps,
    key: (props) => props.experimentId || 'new',
    path: (key) => ['scenes', 'experiment', 'experimentLogic', key],

    connect: {
        values: [
            teamLogic,
            ['currentTeamId'],
            userLogic,
            ['hasAvailableFeature'],
            groupsModel,
            ['groupTypes', 'groupsTaxonomicTypes', 'aggregationLabel'],
        ],
        actions: [experimentsLogic, ['updateExperiments', 'addToExperiments']],
    },
    actions: {
        setExperiment: (experiment: Experiment) => ({ experiment }),
        createExperiment: (draft?: boolean, runningTime?: number, sampleSize?: number) => ({
            draft,
            runningTime,
            sampleSize,
        }),
        setExperimentInsightId: (shortId: InsightShortId) => ({ shortId }),
        createNewExperimentInsight: (filters?: Partial<FilterType>) => ({ filters }),
        setFilters: (filters: Partial<FilterType>) => ({ filters }),
        setNewExperimentData: (experimentData: Partial<Experiment>) => ({ experimentData }),
        updateExperimentGroup: (variant: Partial<MultivariateFlagVariant>, idx: number) => ({ variant, idx }),
        removeExperimentGroup: (idx: number) => ({ idx }),
        setExperimentInsightType: (insightType: InsightType) => ({ insightType }),
        setEditExperiment: (editing: boolean) => ({ editing }),
        setSecondaryMetrics: (secondaryMetrics: SecondaryExperimentMetric[]) => ({ secondaryMetrics }),
        resetNewExperiment: true,
        launchExperiment: true,
        endExperiment: true,
        addExperimentGroup: true,
        archiveExperiment: true,
    },
    reducers: {
        newExperimentData: [
            null as Partial<Experiment> | null,
            {
                setNewExperimentData: (vals, { experimentData }) => {
                    if (experimentData.filters) {
                        const newFilters = { ...vals?.filters, ...experimentData.filters }
                        return { ...vals, ...experimentData, filters: newFilters }
                    }

                    // assuming setNewExperimentData isn't called with new filters & parameters at the same time
                    if (experimentData.parameters) {
                        const newParameters = { ...vals?.parameters, ...experimentData.parameters }
                        return { ...vals, ...experimentData, parameters: newParameters }
                    }
                    return { ...vals, ...experimentData }
                },
                updateExperimentGroup: (state, { variant, idx }) => {
                    const featureFlagVariants = [...(state?.parameters?.feature_flag_variants || [])]
                    featureFlagVariants[idx] = { ...featureFlagVariants[idx], ...variant }
                    return {
                        ...state,
                        parameters: { ...state?.parameters, feature_flag_variants: featureFlagVariants },
                    }
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
                setSecondaryMetrics: (state, { secondaryMetrics }) => {
                    const metrics = secondaryMetrics.map((metric) => metric)
                    return {
                        ...state,
                        secondary_metrics: metrics,
                    }
                },
                resetNewExperiment: () => ({
                    parameters: {
                        feature_flag_variants: [
                            { key: 'control', rollout_percentage: 50 },
                            { key: 'test', rollout_percentage: 50 },
                        ],
                    },
                }),
            },
        ],
        experimentInsightType: [
            InsightType.TRENDS as InsightType,
            {
                setExperimentInsightType: (_, { insightType }) => insightType,
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
    },
    listeners: ({ values, actions }) => ({
        createExperiment: async ({ draft, runningTime, sampleSize }) => {
            let response: Experiment | null = null
            const isUpdate = !!values.experimentId && values.experimentId !== 'new'
            try {
                if (isUpdate) {
                    response = await api.update(
                        `api/projects/${values.currentTeamId}/experiments/${values.experimentId}`,
                        {
                            ...values.newExperimentData,
                            parameters: {
                                ...values.newExperimentData?.parameters,
                                recommended_running_time: runningTime,
                                recommended_sample_size: sampleSize,
                            },
                            ...(!draft && { start_date: dayjs() }),
                        }
                    )
                    if (response?.id) {
                        actions.updateExperiments(response)
                        router.actions.push(urls.experiment(response.id))
                        return
                    }
                } else {
                    response = await api.create(`api/projects/${values.currentTeamId}/experiments`, {
                        ...values.newExperimentData,
                        parameters: {
                            ...values.newExperimentData?.parameters,
                            recommended_running_time: runningTime,
                            recommended_sample_size: sampleSize,
                        },
                        ...(!draft && { start_date: dayjs() }),
                    })
                    response && eventUsageLogic.actions.reportExperimentCreated(response)
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
            if (values.experimentInsightType === InsightType.FUNNELS) {
                newInsightFilters = cleanFilters({
                    insight: InsightType.FUNNELS,
                    funnel_viz_type: FunnelVizType.Steps,
                    display: ChartDisplayType.FunnelViz,
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
            actions.setNewExperimentData({ filters: { ...newInsight.filters } })
        },
        setFilters: ({ filters }) => {
            if (values.experimentInsightType === InsightType.FUNNELS) {
                funnelLogic.findMounted({ dashboardItemId: values.experimentInsightId })?.actions.setFilters(filters)
            } else {
                trendsLogic.findMounted({ dashboardItemId: values.experimentInsightId })?.actions.setFilters(filters)
            }
        },
        loadExperimentSuccess: async ({ experimentData }) => {
            experimentData && eventUsageLogic.actions.reportExperimentViewed(experimentData)
            actions.setExperimentInsightType(experimentData?.filters.insight || InsightType.FUNNELS)
            if (!experimentData?.start_date) {
                // loading a draft experiment
                actions.setNewExperimentData({ ...experimentData })
                actions.createNewExperimentInsight(experimentData?.filters)
            } else {
                actions.resetNewExperiment()
                actions.loadExperimentResults()
                actions.loadSecondaryMetricResults()
            }
        },
        launchExperiment: async () => {
            const startDate = dayjs()
            actions.updateExperiment({ start_date: startDate.format('YYYY-MM-DDTHH:mm') })
            values.experimentData && eventUsageLogic.actions.reportExperimentLaunched(values.experimentData, startDate)
        },
        endExperiment: async () => {
            const endDate = dayjs()
            actions.updateExperiment({ end_date: endDate.format('YYYY-MM-DDTHH:mm') })
            const duration = endDate.diff(values.experimentData?.start_date, 'second')
            values.experimentData &&
                eventUsageLogic.actions.reportExperimentCompleted(
                    values.experimentData,
                    endDate,
                    duration,
                    values.areResultsSignificant
                )
        },
        archiveExperiment: async () => {
            actions.updateExperiment({ archived: true })
            values.experimentData && eventUsageLogic.actions.reportExperimentArchived(values.experimentData)
        },
        setExperimentInsightType: () => {
            if (values.experimentId === 'new' || values.editingExistingExperiment) {
                actions.createNewExperimentInsight()
            } else {
                actions.createNewExperimentInsight(values.experimentData?.filters)
            }
        },
        updateExperimentSuccess: async ({ experimentData }) => {
            actions.updateExperiments(experimentData)
        },
    }),
    loaders: ({ values }) => ({
        experimentData: [
            null as Experiment | null,
            {
                loadExperiment: async () => {
                    if (values.experimentId && values.experimentId !== 'new') {
                        try {
                            const response = await api.get(
                                `api/projects/${values.currentTeamId}/experiments/${values.experimentId}`
                            )
                            return response as Experiment
                        } catch (error: any) {
                            if (error.status === 404) {
                                router.actions.push(urls.experiments())
                            } else {
                                lemonToast.error(`Failed to load experiment ${values.experimentId}`)
                                throw new Error(`Failed to load experiment ${values.experimentId}`)
                            }
                        }
                    }
                    return null
                },
                updateExperiment: async (update: Partial<Experiment>) => {
                    const response: Experiment = await api.update(
                        `api/projects/${values.currentTeamId}/experiments/${values.experimentId}`,
                        update
                    )
                    return response
                },
            },
        ],
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
                        if (error.code === 'no_data') {
                            return null
                        }

                        lemonToast.error(error.detail || 'Failed to load experiment results')
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
                        (values.experimentData?.secondary_metrics || []).map(async (_, index) => {
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
    }),
    selectors: {
        experimentId: [
            () => [(_, props) => props.experimentId ?? 'new'],
            (experimentId): Experiment['id'] => experimentId,
        ],
        breadcrumbs: [
            (s) => [s.experimentData, s.experimentId],
            (experimentData, experimentId): Breadcrumb[] => [
                {
                    name: 'Experiments',
                    path: urls.experiments(),
                },
                {
                    name: experimentData?.name || 'New',
                    path: urls.experiment(experimentId || 'new'),
                },
            ],
        ],
        variants: [
            (s) => [s.newExperimentData, s.experimentData],
            (newExperimentData, experimentData): MultivariateFlagVariant[] => {
                if (experimentData?.start_date) {
                    return experimentData?.parameters?.feature_flag_variants || []
                }

                return (
                    newExperimentData?.parameters?.feature_flag_variants ||
                    experimentData?.parameters?.feature_flag_variants ||
                    []
                )
            },
        ],
        taxonomicGroupTypesForSelection: [
            (s) => [s.newExperimentData, s.groupsTaxonomicTypes],
            (newExperimentData, groupsTaxonomicTypes): TaxonomicFilterGroupType[] => {
                if (
                    newExperimentData?.filters?.aggregation_group_type_index != null &&
                    groupsTaxonomicTypes.length > 0
                ) {
                    return [groupsTaxonomicTypes[newExperimentData.filters.aggregation_group_type_index]]
                }

                return [TaxonomicFilterGroupType.PersonProperties, TaxonomicFilterGroupType.Cohorts]
            },
        ],
        parsedSecondaryMetrics: [
            (s) => [s.newExperimentData, s.experimentData],
            (newExperimentData: Partial<Experiment>, experimentData: Experiment): SecondaryExperimentMetric[] => {
                const secondaryMetrics = newExperimentData?.secondary_metrics || experimentData?.secondary_metrics || []
                return secondaryMetrics
            },
        ],
        minimumDetectableChange: [
            (s) => [s.newExperimentData],
            (newExperimentData): number => {
                return newExperimentData?.parameters?.minimum_detectable_effect || 5
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
                    const errorResult = "Can't find variant"
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
                    const errorResult = "Can't find variant"
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
    },
    urlToAction: ({ actions, values }) => ({
        '/experiments/:id': ({ id }, _, __, currentLocation, previousLocation) => {
            if (!values.hasAvailableFeature(AvailableFeature.EXPERIMENTATION)) {
                router.actions.push('/experiments')
                return
            }
            const didPathChange = currentLocation.initial || currentLocation.pathname !== previousLocation?.pathname
            if (id && didPathChange) {
                const parsedId = id === 'new' ? 'new' : parseInt(id)
                if (parsedId === 'new') {
                    actions.createNewExperimentInsight()
                    actions.resetNewExperiment()
                    actions.setSecondaryMetrics([])
                }

                actions.setEditExperiment(false)

                if (parsedId !== 'new' && parsedId === values.experimentId) {
                    actions.loadExperiment()
                }
            }
        },
    }),
})

function percentageDistribution(variantCount: number): number[] {
    const percentageRounded = Math.round(100 / variantCount)
    const totalRounded = percentageRounded * variantCount
    const delta = totalRounded - 100
    const percentages = new Array(variantCount).fill(percentageRounded)
    percentages[variantCount - 1] = percentageRounded - delta
    return percentages
}
