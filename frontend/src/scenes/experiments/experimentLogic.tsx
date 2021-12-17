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
} from '~/types'
import { experimentLogicType } from './experimentLogicType'
import { router } from 'kea-router'
import { experimentsLogic } from './experimentsLogic'
import { FunnelLayout } from 'lib/constants'

const DEFAULT_DURATION = 14 // days

export const experimentLogic = kea<experimentLogicType>({
    path: ['scenes', 'experiment', 'experimentLogic'],
    connect: { values: [teamLogic, ['currentTeamId']], actions: [experimentsLogic, ['loadExperiments']] },
    actions: {
        setExperimentResults: (experimentResults: ExperimentResults | null) => ({ experimentResults }),
        setExperiment: (experiment: Experiment) => ({ experiment }),
        createExperiment: (draft?: boolean, runningTime?: number, sampleSize?: number) => ({
            draft,
            runningTime,
            sampleSize,
        }),
        setExperimentFunnelId: (shortId: InsightShortId) => ({ shortId }),
        createNewExperimentFunnel: (filters?: Partial<FilterType>) => ({ filters }),
        setFilters: (filters: Partial<FilterType>) => ({ filters }),
        setExperimentId: (experimentId: number | 'new') => ({ experimentId }),
        setNewExperimentData: (experimentData: Partial<Experiment>) => ({ experimentData }),
        emptyData: true,
        launchExperiment: true,
        endExperiment: true,
        editExperiment: true,
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
                emptyData: () => null,
            },
        ],
        experimentResults: [
            null as ExperimentResults | null,
            {
                setExperimentResults: (_, { experimentResults }) => experimentResults,
            },
        ],
        experimentFunnelId: [
            null as InsightShortId | null,
            {
                setExperimentFunnelId: (_, { shortId }) => shortId,
            },
        ],
        editingExistingExperiment: [
            false,
            {
                editExperiment: () => true,
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
                toast.success(
                    <div data-attr="success-toast">
                        <h1>Experiment {isUpdate ? 'updated' : 'created'} successfully!</h1>
                        {!isUpdate && <p>Click here to launch this experiment.</p>}
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
        createNewExperimentFunnel: async ({ filters }) => {
            const newInsight = {
                name: generateRandomAnimal(),
                description: '',
                tags: [],
                filters: cleanFilters({
                    insight: InsightType.FUNNELS,
                    funnel_viz_type: FunnelVizType.Steps,
                    date_from: dayjs().subtract(DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                    layout: FunnelLayout.horizontal,
                    ...filters,
                }),
                result: null,
            }
            const createdInsight: InsightModel = await api.create(
                `api/projects/${teamLogic.values.currentTeamId}/insights`,
                newInsight
            )
            actions.setExperimentFunnelId(createdInsight.short_id)
        },
        setFilters: ({ filters }) => {
            funnelLogic.findMounted({ dashboardItemId: values.experimentFunnelId })?.actions.setFilters(filters)
        },
        loadExperimentSuccess: async ({ experimentData }) => {
            if (!experimentData?.start_date) {
                // loading a draft mode experiment
                actions.createNewExperimentFunnel(experimentData?.filters)
                actions.setNewExperimentData({ ...experimentData })
            } else {
                try {
                    const response = await api.get(
                        `api/projects/${values.currentTeamId}/experiments/${values.experimentId}/results`
                    )
                    actions.setExperimentResults({ ...response, itemID: Math.random().toString(36).substring(2, 15) })
                } catch (error) {
                    if (error.code === 'no_data') {
                        actions.setExperimentResults({
                            funnel: [],
                            filters: {},
                            probability: 0,
                            itemID: Math.random().toString(36).substring(2, 15),
                        })
                        return
                    }

                    errorToast(
                        'Error loading experiment results',
                        'Attempting to load results returned an error:',
                        error.status !== 0
                            ? error.detail
                            : "Check your internet connection and make sure you don't have an extension blocking our requests.",
                        error.code
                    )
                    actions.setExperimentResults(null)
                }
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
            await api.update(`api/projects/${values.currentTeamId}/experiments/${values.experimentId}`, {
                end_date: dayjs(),
            })
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
        minimumDetectableChange: [
            (s) => [s.newExperimentData],
            (newExperimentData): number => {
                return newExperimentData?.parameters?.minimum_detectable_effect || 5
            },
        ],
        recommendedSampleSize: [
            (s) => [s.minimumDetectableChange],
            (mde) => (conversionRate: number) => {
                // Using the rule of thumb: 16 * sigma^2 / (mde^2)
                // refer https://en.wikipedia.org/wiki/Sample_size_determination with default beta and alpha
                // The results are same as: https://www.evanmiller.org/ab-testing/sample-size.html
                // and also: https://marketing.dynamicyield.com/ab-test-duration-calculator/
                // this is per variant, so we need to multiply by 2
                return 2 * Math.ceil((1600 * conversionRate * (1 - conversionRate / 100)) / (mde * mde))
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
                    const variantResults = experimentResults.funnel.find(
                        (variantFunnel) => variantFunnel[0].breakdown_value?.[0] === variant
                    )
                    if (!variantResults) {
                        return errorResult
                    }
                    return `${(
                        (variantResults[variantResults.length - 1].count / variantResults[0].count) *
                        100
                    ).toFixed(1)}%`
                },
        ],
    },
    urlToAction: ({ actions, values }) => ({
        '/experiments/:id': ({ id }) => {
            if (id) {
                const parsedId = id === 'new' ? 'new' : parseInt(id)
                // TODO: optimise loading if already loaded Experiment
                // like in featureFlagLogic.tsx
                if (parsedId === 'new') {
                    actions.createNewExperimentFunnel()
                    actions.emptyData()
                }
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
