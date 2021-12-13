import { kea } from 'kea'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { generateRandomAnimal } from 'lib/utils/randomAnimal'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { Experiment, InsightType, InsightModel, FunnelVizType, Breadcrumb, InsightShortId } from '~/types'

import { experimentLogicType } from './experimentLogicType'
import { experimentsLogic } from './experimentsLogic'

export const experimentLogic = kea<experimentLogicType>({
    path: ['scenes', 'experiment', 'experimentLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    actions: {
        setExperiment: (experiment: Experiment) => ({ experiment }),
        createExperiment: (draft?: boolean) => ({ draft }),
        setExperimentFunnelId: (shortId: InsightShortId) => ({ shortId }),
        createNewExperimentFunnel: true,
        setFilters: (filters) => ({ filters }),
        setExperimentId: (experimentId: number | 'new') => ({ experimentId }),
        setNewExperimentData: (experimentData: Partial<Experiment>) => ({ experimentData }),
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
            },
        ],
        experimentFunnelId: [
            null as InsightShortId | null,
            {
                setExperimentFunnelId: (_, { shortId }) => shortId,
            },
        ],
    },
    listeners: ({ values, actions }) => ({
        createExperiment: async ({ draft }) => {
            await api.create(`api/projects/${values.currentTeamId}/experiments`, {
                ...values.newExperimentData,
                ...(!draft && { start_date: dayjs() }),
            })
            experimentsLogic.actions.loadExperiments()
        },
        createNewExperimentFunnel: async () => {
            const newInsight = {
                name: generateRandomAnimal(),
                description: '',
                tags: [],
                filters: cleanFilters({ insight: InsightType.FUNNELS, funnel_viz_type: FunnelVizType.Steps }),
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
                return (1600 * conversionRate * (1 - conversionRate / 100)) / (mde * mde)
            },
        ],
        expectedRunningTime: [
            () => [],
            () =>
                (entrants: number, sampleSize: number): number => {
                    // TODO: connect to broken insight date filter
                    const time = 7 // days
                    return (sampleSize / entrants) * time
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
    actionToUrl: () => ({
        createExperiment: () => '/experiments',
    }),
})
