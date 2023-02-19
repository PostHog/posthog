import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { DashboardTemplateType } from '~/types'

import type { newDashboardTemplateLogicType } from './NewDashboardTemplateLogicType'

export const newDashboardTemplateLogic = kea<newDashboardTemplateLogicType>([
    path(['scenes', 'dashboard', 'NewDashboardTemplateLogic']),
    actions({
        setDashboardTemplateJSON: (dashboardTemplateJSON: string) => ({ dashboardTemplateJSON }),
        setOpenNewDashboardTemplateModal: (openNewDashboardTemplateModal: boolean) => ({
            openNewDashboardTemplateModal,
        }),
        createDashboardTemplate: (dashboardTemplateJSON: string) => ({ dashboardTemplateJSON }),
    }),
    reducers({
        dashboardTemplateJSON: [
            '' as string,
            {
                setDashboardTemplateJSON: (_, { dashboardTemplateJSON }) => dashboardTemplateJSON,
            },
        ],
        isOpenNewDashboardTemplateModal: [
            false as boolean,
            {
                setOpenNewDashboardTemplateModal: (_, { openNewDashboardTemplateModal }) =>
                    openNewDashboardTemplateModal,
            },
        ],
    }),
    loaders(({ values }) => ({
        dashboardTemplate: [
            null as DashboardTemplateType | null,
            {
                createDashboardTemplate: async () => {
                    const response = await api.create(
                        '/api/projects/@current/dashboard_templates',
                        JSON.parse(values.dashboardTemplateJSON)
                    )
                    return response
                },
            },
        ],
    })),
])
