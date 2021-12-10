import { kea } from 'kea'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { generateRandomAnimal } from 'lib/utils/randomAnimal'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { findInsightFromMountedLogic } from 'scenes/insights/utils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { teamLogic } from 'scenes/teamLogic'
import { Experiment, InsightType, InsightModel, FunnelVizType, FunnelStep } from '~/types'

import { experimentLogicType } from './experimentLogicType'
import { experimentsLogic } from './experimentsLogic'

export const experimentLogic = kea<experimentLogicType>({
    path: ['scenes', 'experiment', 'experimentLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    actions: {
        setExperiment: (experiment: Experiment) => ({ experiment }),
        createExperiment: (draft?: boolean) => ({ draft }),
        setExperimentFunnel: (funnel: InsightModel) => ({ funnel }),
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
                    console.log(experimentData)
                    return { ...vals, ...experimentData }
                },
            },
        ],
        experimentFunnel: [
            null as InsightModel | null,
            {
                setExperimentFunnel: (_, { funnel }) => funnel,
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
            actions.setExperimentFunnel(createdInsight)
        },
        setFilters: ({ filters }) => {
            funnelLogic.findMounted({ dashboardItemId: values.experimentFunnel?.short_id })?.actions.setFilters(filters)
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
        minimimumDetectableChange: [
            (s) => [s.newExperimentData],
            (newExperimentData): number => {
                console.log('changing med', newExperimentData)
                return newExperimentData?.parameters?.minimum_detectable_change || 5
            },
        ],
        insight: [
            (s) => [s.experimentFunnel],
            (experimentFunnel) => {
                if (!experimentFunnel?.short_id) {return undefined}

                const insight = findInsightFromMountedLogic(experimentFunnel.short_id, undefined)
                console.log(insight?.result)
                return insight
            },
        ],
        experimentFunnelConversionRate: [
            (s) => [s.experimentFunnel],
            (experimentFunnel) => (experimentResult: FunnelStep[]) => {
                console.log(experimentFunnel)
                return experimentResult[0]?.average_conversion_time || 20
            },
        ],
        recommendedSampleSize: [
            (s) => [s.experimentFunnel, s.minimimumDetectableChange],
            (funnel, mde): number => {
                console.log(funnel, mde)
                const conversionRate = funnel?.result?.slice[-1]?.average_conversion_time || 20
                return (1600 * conversionRate * (1 - conversionRate / 100)) / (mde * mde)
            },
        ],
        expectedRunningTime: [
            (s) => [s.experimentFunnel, s.recommendedSampleSize],
            (funnel, sampleSize): number => {
                const funnelEntrants = funnel?.result[0]?.count
                const time = 7 // days
                return (sampleSize / funnelEntrants) * time
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
