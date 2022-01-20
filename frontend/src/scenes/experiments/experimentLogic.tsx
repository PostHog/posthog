import { kea } from 'kea'
import React from 'react'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { errorToast } from 'lib/utils'
import { generateRandomAnimal } from 'lib/utils/randomAnimal'
import { toast } from 'react-toastify'
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
} from '~/types'
import { experimentLogicType } from './experimentLogicType'
import { router } from 'kea-router'
import { experimentsLogic } from './experimentsLogic'
import { FunnelLayout } from 'lib/constants'
import { trendsLogic } from 'scenes/trends/trendsLogic'

const DEFAULT_DURATION = 14 // days

export const experimentLogic = kea<experimentLogicType>({
    path: ['scenes', 'experiment', 'experimentLogic'],
    connect: {
        values: [teamLogic, ['currentTeamId']],
        actions: [experimentsLogic, ['updateExperiment', 'addToExperiments']],
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
        setExperimentId: (experimentId: number | 'new') => ({ experimentId }),
        setNewExperimentData: (experimentData: Partial<Experiment>) => ({ experimentData }),
        updateExperimentGroup: (variant: MultivariateFlagVariant, idx: number) => ({ variant, idx }),
        removeExperimentGroup: (idx: number) => ({ idx }),
        setExperimentInsightType: (insightType: InsightType) => ({ insightType }),
        setEditExperiment: (editing: boolean) => ({ editing }),
        resetNewExperiment: true,
        launchExperiment: true,
        endExperiment: true,
        addExperimentGroup: true,
    },
    reducers: {
        experimentId: [
            null as number | 'new' | null,
            {
                setExperimentId: (_, { experimentId }) => experimentId,
            },
        ],
        newExperimentData: [
            null as Partial<Experiment> | null,
            {
                setNewExperimentData: (vals, { experimentData }) => {
                    if (experimentData.filters) {
                        const newFilters = { ...vals?.filters, ...experimentData.filters }
                        return { ...vals, ...experimentData, filters: newFilters }
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
                        state?.parameters?.feature_flag_variants.length - 1
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
            InsightType.FUNNELS as InsightType,
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
            const isUpdate = !!values.newExperimentData?.id
            try {
                if (values.newExperimentData?.id) {
                    response = await api.update(
                        `api/projects/${values.currentTeamId}/experiments/${values.experimentId}`,
                        {
                            ...values.newExperimentData,
                            parameters: {
                                ...values.newExperimentData.parameters,
                                recommended_running_time: runningTime,
                                recommended_sample_size: sampleSize,
                            },
                            ...(!draft && { start_date: dayjs() }),
                        }
                    )
                    if (response?.id) {
                        actions.updateExperiment(response)
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
                }
            } catch (error) {
                errorToast(
                    'Error creating your experiment',
                    'Attempting to create this experiment returned an error:',
                    error.status !== 0
                        ? error.detail
                        : "Check your internet connection and make sure you don't have an extension blocking our requests.",
                    error.code
                )
                return
            }

            if (response?.id) {
                const experimentId = response.id
                router.actions.push(urls.experiment(experimentId))
                actions.addToExperiments(response)
                toast.success(
                    <div data-attr="success-toast">
                        <h1>Experiment {isUpdate ? 'updated' : 'created'} successfully!</h1>
                        {!isUpdate && <p>Click here to view this experiment.</p>}
                    </div>,
                    {
                        onClick: () => {
                            router.actions.push(urls.experiment(experimentId))
                        },
                        closeOnClick: true,
                        onClose: () => {
                            router.actions.push(urls.experiment(experimentId))
                        },
                    }
                )
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
                name: generateRandomAnimal(),
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
            actions.setExperimentInsightType(experimentData?.filters.insight || InsightType.FUNNELS)
            if (!experimentData?.start_date) {
                // loading a draft mode experiment
                actions.setNewExperimentData({ ...experimentData })
                actions.createNewExperimentInsight(experimentData?.filters)
            } else {
                actions.loadExperimentResults()
            }
        },
        launchExperiment: async () => {
            const response: Experiment = await api.update(
                `api/projects/${values.currentTeamId}/experiments/${values.experimentId}`,
                {
                    start_date: dayjs(),
                }
            )
            actions.setExperimentId(response.id || 'new')
            actions.loadExperiment()
        },
        endExperiment: async () => {
            const response: Experiment = await api.update(
                `api/projects/${values.currentTeamId}/experiments/${values.experimentId}`,
                {
                    end_date: dayjs(),
                }
            )
            actions.setExperimentId(response.id || 'new')
            actions.loadExperiment()
        },
        setExperimentInsightType: () => {
            if (values.experimentId === 'new') {
                actions.createNewExperimentInsight()
            } else {
                if (values.editingExistingExperiment) {
                    actions.createNewExperimentInsight()
                    return
                }
                actions.createNewExperimentInsight(values.experimentData?.filters)
            }
        },
    }),
    loaders: ({ values }) => ({
        experimentData: [
            null as Experiment | null,
            {
                loadExperiment: async () => {
                    if (values.experimentId && values.experimentId !== 'new') {
                        const response = await api.get(
                            `api/projects/${values.currentTeamId}/experiments/${values.experimentId}`
                        )
                        return response as Experiment
                    }
                    return null
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
                    } catch (error) {
                        if (error.code === 'no_data') {
                            return null
                        }

                        errorToast(
                            'Error loading experiment results',
                            'Attempting to load results returned an error:',
                            error.status !== 0
                                ? error.detail
                                : "Check your internet connection and make sure you don't have an extension blocking our requests.",
                            error.code
                        )
                        return null
                    }
                },
                emptyExperimentResults: () => null,
            },
        ],
    }),
    selectors: {
        breadcrumbs: [
            (s) => [s.experimentData, s.experimentId],
            (experimentData, experimentId): Breadcrumb[] => [
                {
                    name: 'Experiments',
                    path: urls.experiments(),
                },
                {
                    name: experimentData?.name || 'New Experiment',
                    path: urls.experiment(experimentId || 'new'),
                },
            ],
        ],
        variants: [
            (s) => [s.newExperimentData, s.experimentData],
            (newExperimentData, experimentData): MultivariateFlagVariant[] => {
                return (
                    newExperimentData?.parameters?.feature_flag_variants ||
                    experimentData?.parameters?.feature_flag_variants ||
                    []
                )
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
        mdeGivenSampleSizeAndConversionRate: [
            () => [],
            () =>
                (sampleSize: number, conversionRate: number): number => {
                    return Math.sqrt((1600 * conversionRate * (1 - conversionRate / 100)) / sampleSize)
                },
        ],
        mdeGivenCountData: [
            () => [],
            () =>
                (controlCountData: number): number => {
                    // ref http://www.columbia.edu/~cjd11/charles_dimaggio/DIRE/styled-4/code-12/
                    // 4*sqrt(lambda*)

                    // background rates:
                    // roughly matches significance for https://www.evanmiller.org/ab-testing/poisson-means.html
                    return Math.ceil(2 * Math.sqrt(2) * Math.sqrt(controlCountData))
                },
        ],
        bestConversionVariant: [
            (s) => [s.variants, s.conversionRateForVariant],
            (variants, conversionRateForVariant): { variant: MultivariateFlagVariant; value: number } => {
                const bestVariant = variants.reduce(
                    (best, variant) => {
                        const value = parseFloat(conversionRateForVariant(variant.key))
                        if (value > best.value) {
                            return { variant, value }
                        }
                        return best
                    },
                    { variant: { key: '', rollout_percentage: 0 }, value: 0 }
                )
                return bestVariant
            },
        ],
        bestCountVariant: [
            (s) => [s.variants, s.countDataForVariant],
            (variants, countDataForVariant): { variant: MultivariateFlagVariant; value: number } => {
                const bestVariant = variants.reduce(
                    (best, variant) => {
                        const value = parseInt(countDataForVariant(variant.key))
                        if (value && value > best.value) {
                            return { variant, value }
                        }
                        return best
                    },
                    { variant: { key: '', rollout_percentage: 0 }, value: 0 }
                )
                return bestVariant
            },
        ],
        areCountResultsSignificant: [
            (s) => [s.mdeGivenCountData, s.bestCountVariant, s.countDataForVariant],
            (mdeGivenCountData, bestCountVariant, countDataForVariant): boolean => {
                const targetCountData = bestCountVariant.value
                const controlCountData = parseInt(countDataForVariant('control'))
                // minimum detectable effect for variant determines significance
                return Math.abs(targetCountData - controlCountData) > mdeGivenCountData(controlCountData)
            },
        ],
        areConversionResultsSignificant: [
            (s) => [
                s.mdeGivenSampleSizeAndConversionRate,
                s.bestConversionVariant,
                s.conversionRateForVariant,
                s.experimentResults,
            ],
            (
                mdeGivenSampleSizeAndConversionRate,
                bestConversionVariant,
                conversionRateForVariant,
                experimentResults
            ): boolean => {
                if (!experimentResults) {
                    return false
                }

                const controlResults = (experimentResults?.insight as FunnelStep[][]).find(
                    (variantFunnel: FunnelStep[]) => variantFunnel[0]?.breakdown_value?.[0] === 'control'
                )
                if (!controlResults) {
                    return false
                }
                const sampleSizeForControl = controlResults[0].count
                if (!sampleSizeForControl) {
                    return false
                }
                const targetConversionRate = bestConversionVariant.value
                const controlConversionRate = parseFloat(conversionRateForVariant('control'))
                // minimum detectable effect for variant determines significance
                return (
                    Math.abs(targetConversionRate - controlConversionRate) >
                    mdeGivenSampleSizeAndConversionRate(sampleSizeForControl, controlConversionRate)
                )
            },
        ],
        recommendedExposureForCountData: [
            () => [],
            () =>
                (baseCountData: number): number => {
                    // assume a 5% mde, target count data is 5% of base count data
                    // http://www.columbia.edu/~cjd11/charles_dimaggio/DIRE/styled-4/code-12/
                    const minCountData = baseCountData * 0.05
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
                (entrants: number, sampleSize: number): number => {
                    // recommended people / (actual people / day) = expected days
                    return parseFloat((sampleSize / (entrants / DEFAULT_DURATION)).toFixed(1))
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
    },
    urlToAction: ({ actions, values }) => ({
        '/experiments/:id': ({ id }) => {
            actions.emptyExperimentResults()
            if (id) {
                const parsedId = id === 'new' ? 'new' : parseInt(id)
                // TODO: optimise loading if already loaded Experiment
                // like in featureFlagLogic.tsx
                if (parsedId === 'new') {
                    actions.createNewExperimentInsight()
                    actions.resetNewExperiment()
                }

                actions.setEditExperiment(false)

                if (parsedId !== values.experimentId) {
                    actions.setExperimentId(parsedId)
                }
                if (parsedId !== 'new') {
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
