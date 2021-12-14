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
import { Experiment, InsightType, InsightModel, FunnelVizType, Breadcrumb, InsightShortId, FilterType } from '~/types'

import { experimentLogicType } from './experimentLogicType'
import { router } from 'kea-router'
import { experimentsLogic } from './experimentsLogic'

export const experimentLogic = kea<experimentLogicType>({
    path: ['scenes', 'experiment', 'experimentLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    actions: {
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
                        experimentsLogic.actions.loadExperiments()
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
                    date_from: dayjs().subtract(14, 'day').format('YYYY-MM-DDTHH:mm'),
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
    selectors: ({ values }) => ({
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
        funnel: [
            (s) => [
                funnelLogic({ dashboardItemId: values.experimentFunnelId, syncWithUrl: false }).selectors.results,
                s.newExperimentData,
            ],
            (results) => {
                // eslint-disable-line
                const newResults = funnelLogic.findMounted({ dashboardItemId: values.experimentFunnelId })?.values
                    .results // valid results
                const newResultsWithoutFound = funnelLogic({
                    dashboardItemId: values.experimentFunnelId,
                    syncWithUrl: false,
                })?.values.results // valid results
                console.log('id: ', values.experimentFunnelId, results, newResults, newResultsWithoutFound)
                // results is empty??
                return results
            },
        ],
        minimimumDetectableChange: [
            (s) => [s.newExperimentData],
            (newExperimentData): number => {
                const med = newExperimentData?.parameters?.minimum_detectable_effect || 5
                return med
            },
        ],
        experimentFunnelConversionRate: [
            (s) => [s.funnel],
            (funnelResult): number => {
                console.log('conversion rate change: ', funnelResult)
                return funnelResult?.[0]?.average_conversion_time || 20
            },
        ],
        recommendedSampleSize: [
            (s) => [s.minimimumDetectableChange],
            (mde) => (conversionRate: number) => {
                return Math.ceil((1600 * conversionRate * (1 - conversionRate / 100)) / (mde * mde))
            },
        ],
        expectedRunningTime: [
            () => [],
            () =>
                (entrants: number, sampleSize: number): number => {
                    // TODO: connect to broken insight date filter
                    const time = 7 // days
                    return parseFloat(((sampleSize / entrants) * time).toFixed(1))
                },
        ],
    }),
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
