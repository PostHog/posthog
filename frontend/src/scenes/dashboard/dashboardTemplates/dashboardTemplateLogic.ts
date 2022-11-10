import { kea, path } from 'kea'

import type { dashboardTemplateLogicType } from './dashboardTemplateLogicType'
import { loaders } from 'kea-loaders'
import { DashboardType } from '~/types'

export const dashboardTemplateLogic = kea<dashboardTemplateLogicType>([
    path(['scenes', 'dashboard', 'dashboardTemplates', 'dashboardTemplateLogic']),
    loaders({
        dashboardTemplate: [
            null,
            {
                saveDashboardTemplate: async ({
                    templateName,
                    dashboard,
                }: {
                    templateName: string
                    dashboard: DashboardType
                }) => {
                    console.log('saving', templateName, dashboard)
                    return null
                },
            },
        ],
    }),
])
