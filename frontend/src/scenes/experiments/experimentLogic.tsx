import { kea } from 'kea'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { generateRandomAnimal } from 'lib/utils/randomAnimal'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { teamLogic } from 'scenes/teamLogic'
import { Experiment, InsightType } from '~/types'
import { DashboardItemType } from '~/types'

import { experimentLogicType } from './experimentLogicType'

export const experimentLogic = kea<experimentLogicType>({
    path: ['scenes', 'experiment', 'experimentLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    actions: {
        setExperiment: (experiment: Experiment) => ({ experiment }),
        createExperiment: (draft?: boolean) => ({ draft }),
        setFunnelProps: (funnelProps: any) => ({ funnelProps }),
        setExperimentFunnel: (funnel: DashboardItemType) => ({ funnel }),
        createNewExperimentFunnel: true,
        setFilters: (filters) => ({ filters }),
        setExperimentId: (experimentId: number | 'new') => ({ experimentId }),
        setNewExperimentData: (experimentData: Experiment) => ({ experimentData }),
    },
    reducers: {
        experimentId: [
            null as number | 'new' | null,
            {
                setExperimentId: (_, { experimentId }) => experimentId,
            },
        ],
        newExperimentData: [
            null as Experiment | null,
            {
                setNewExperimentData: (_, { experimentData }) => experimentData,
            },
        ],
        experimentFunnel: [
            null as DashboardItemType | null,
            {
                setExperimentFunnel: (_, { funnel }) => funnel,
            },
        ],
        funnelProps: [
            { dashboardItemId: undefined, syncWithUrl: false, filters: {}, result: [] },
            {
                setFunnelProps: (_, { funnelProps }) => funnelProps,
            },
        ],
    },
    listeners: ({ values, actions }) => ({
        createExperiment: async ({ draft }) => {
            await api.create(`api/projects/${values.currentTeamId}/experiments`, {
                ...values.newExperimentData,
                ...(draft && { start_date: dayjs() }),
            })
        },
        createNewExperimentFunnel: async () => {
            const newInsight = {
                name: generateRandomAnimal(),
                description: '',
                tags: [],
                filters: cleanFilters({ insight: InsightType.FUNNELS }),
                result: null,
            }
            const createdInsight: DashboardItemType = await api.create(
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
                        console.log(response)
                        return response as Experiment
                    }
                    return null
                },
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
})
