import { kea } from 'kea'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { generateRandomAnimal } from 'lib/utils/randomAnimal'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { teamLogic } from 'scenes/teamLogic'
import { DashboardItemType, Experiment, InsightType } from '~/types'

import { experimentLogicType } from './experimentLogicType'
export const experimentLogic = kea<experimentLogicType>({
    path: ['scenes', 'experiment', 'experimentLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    actions: {
        setExperiment: (experiment: Experiment) => ({ experiment }),
        createExperiment: (draft?: boolean) => ({ draft }),
        setFunnelProps: (funnelProps: any) => ({ funnelProps }),
    },
    loaders: ({ actions }) => ({
        funnelInsight: [
            null,
            {
                loadFunnelInsight: async () => {
                    const filters = { insight: InsightType.FUNNELS }
                    const newInsight = {
                        name: generateRandomAnimal(),
                        description: '',
                        tags: [],
                        filters: cleanFilters(filters || {}),
                        result: null,
                    }
                    const createdInsight: DashboardItemType = await api.create(
                        `api/projects/${teamLogic.values.currentTeamId}/insights`,
                        newInsight
                    )
                    actions.setFunnelProps({
                        dashboardItemId: createdInsight.short_id,
                        filters: createdInsight.filters,
                    })
                    return createdInsight
                },
            },
        ],
    }),
    reducers: {
        experiment: [
            null as Experiment | null,
            {
                setExperiment: (_, { experiment }) => experiment,
            },
        ],
        funnelProps: [
            { dashboardItemId: undefined, syncWithUrl: false, filters: {}, result: [] },
            {
                setFunnelProps: (_, { funnelProps }) => funnelProps,
            },
        ],
    },
    listeners: ({ values }) => ({
        createExperiment: async ({ draft }) => {
            await api.create(`api/projects/${values.currentTeamId}/experiments`, {
                ...values.experiment,
                ...(draft && { start_date: dayjs() }),
            })
        },
    }),
    events: ({ actions }) => ({
        afterMount: [actions.loadFunnelInsight],
    }),
})
