import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { DashboardTemplatesRepositoryEntry } from 'scenes/dashboard/dashboards/templates/types'

import type { dashboardTemplatesLogicType } from './dashboardTemplatesLogicType'

export const dashboardTemplatesLogic = kea<dashboardTemplatesLogicType>([
    path(['scenes', 'dashboard', 'dashboards', 'templates', 'dashboardTemplatesLogic']),
    loaders({
        repository: [
            {} as Record<string, DashboardTemplatesRepositoryEntry>,
            {
                loadRepository: async () => {
                    const results = await api.get('api/projects/@current/dashboard_templates/repository')
                    const repository: Record<string, DashboardTemplatesRepositoryEntry> = {}
                    for (const template of results as DashboardTemplatesRepositoryEntry[]) {
                        if (template.url) {
                            repository[template.url.replace(/\/+$/, '')] = template
                        }
                    }
                    return repository
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadRepository()
    }),
])
