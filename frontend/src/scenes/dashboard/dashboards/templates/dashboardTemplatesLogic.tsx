import { actions, afterMount, connect, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { DashboardTemplateScope, DashboardTemplateType } from '~/types'

import type { dashboardTemplatesLogicType } from './dashboardTemplatesLogicType'

export interface DashboardTemplateProps {
    scope?: DashboardTemplateScope
}

export const dashboardTemplatesLogic = kea<dashboardTemplatesLogicType>([
    path(['scenes', 'dashboard', 'dashboards', 'templates', 'dashboardTemplatesLogic']),
    props({} as DashboardTemplateProps),
    key(({ scope }) => scope ?? 'unknown'),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),
    actions({
        setTemplates: (allTemplates: DashboardTemplateType[]) => ({ allTemplates }),
    }),
    loaders(({ props }) => ({
        allTemplates: [
            [] as DashboardTemplateType[],
            {
                getAllTemplates: async () => {
                    const page = await api.dashboardTemplates.list(props)
                    return page.results
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.getAllTemplates()
    }),
])
