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

const DEFAULT_DURATION = 14 // days

export const experimentLogic = kea<experimentLogicType>({
    path: ['scenes', 'experiment', 'experimentLogic'],
    connect: { values: [teamLogic, ['currentTeamId']], actions: [experimentsLogic, ['loadExperiments']] },
    actions: {
        setExperimentResults: (experimentResults: ExperimentResults | null) => ({ experimentResults }),
        setExperiment: (experiment: Experiment) => ({ experiment }),
        createExperiment: (draft?: boolean) => ({ draft }),
        setExperimentFunnelId: (shortId: InsightShortId) => ({ shortId }),
        createNewExperimentFunnel: (filters?: Partial<FilterType>) => ({ filters }),
        setFilters: (filters: Partial<FilterType>) => ({ filters }),
        setExperimentId: (experimentId: number | 'new') => ({ experimentId }),
        setNewExperimentData: (experimentData: Partial<Experiment>) => ({ experimentData }),
        nextPage: true,
        prevPage: true,
        setPage: (page: number) => ({ page }),
        emptyData: true,
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
        newExperimentCurrentPage: [
            0,
            {
                nextPage: (page) => page + 1,
                prevPage: (page) => page - 1,
                setPage: (_, { page }) => page,
            },
        ],
    },
    listeners: ({ values, actions }) => ({
        createExperiment: async ({ draft }) => {
            try {
                if (values.newExperimentData?.id) {
                    await api.update(`api/projects/${values.currentTeamId}/experiments/${values.experimentId}`, {
                        start_date: dayjs(),
                    })
                } else {
                    await api.create(`api/projects/${values.currentTeamId}/experiments`, {
                        ...values.newExperimentData,
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
            toast.success(
                <div data-attr="success-toast">
                    <h1>Experimentation created successfully!</h1>
                    <p>Click here to go back to the experiments list.</p>
                </div>,
                {
                    onClick: () => {
                        actions.loadExperiments()
                        router.actions.push(urls.experiments())
                    },
                    closeOnClick: true,
                }
            )
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
        loadExperiment: async () => {
            try {
                const response = await api.get(
                    `api/projects/${values.currentTeamId}/experiments/${values.experimentId}/results`
                )
                actions.setExperimentResults({ ...response, itemID: Math.random().toString(36).substring(2, 15) })
            } catch (error) {
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
        },
        setFilters: ({ filters }) => {
            funnelLogic.findMounted({ dashboardItemId: values.experimentFunnelId })?.actions.setFilters(filters)
        },
        loadExperimentSuccess: ({ experimentData }) => {
            if (!experimentData?.start_date) {
                // loading a draft mode experiment
                actions.createNewExperimentFunnel(experimentData?.filters)
                actions.setPage(2)
                actions.setNewExperimentData({ ...experimentData })
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
        minimimumDetectableChange: [
            (s) => [s.newExperimentData],
            (newExperimentData): number => {
                return newExperimentData?.parameters?.minimum_detectable_effect || 5
            },
        ],
        recommendedSampleSize: [
            (s) => [s.minimimumDetectableChange],
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
                    actions.setPage(0)
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
