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
    },
    reducers: {
        experiment: [
            null as Experiment | null,
            {
                setExperiment: (_, { experiment }) => experiment,
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
                ...values.experiment,
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
})
