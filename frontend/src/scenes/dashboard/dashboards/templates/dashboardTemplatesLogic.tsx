import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { DashboardTemplatesRepositoryEntry } from 'scenes/dashboard/dashboards/templates/types'

import type { dashboardTemplatesLogicType } from './dashboardTemplatesLogicType'
import { LemonSelectOption } from 'lib/lemon-ui/LemonSelect'
import { DashboardTemplateType } from '~/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export const dashboardTemplatesLogic = kea<dashboardTemplatesLogicType>([
    path(['scenes', 'dashboard', 'dashboards', 'templates', 'dashboardTemplatesLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),
    actions({
        setTemplates: (allTemplates: DashboardTemplateType[]) => ({ allTemplates }),
    }),
    loaders({
        repository: [
            {} as Record<string, DashboardTemplatesRepositoryEntry>,
            {
                loadRepository: async () => {
                    return api.dashboardTemplates.repository()
                },
            },
        ],
        template: [
            null,
            {
                installTemplate: async (payload: { name: string; url: string }) => {
                    return await api.create('api/projects/@current/dashboard_templates/', payload)
                },
            },
        ],
        allTemplates: [
            [] as DashboardTemplateType[],
            {
                getAllTemplates: async () => {
                    const page = await api.dashboardTemplates.list()
                    return page.results
                },
            },
        ],
    }),
    reducers(() => ({
        templateBeingSaved: [
            null as string | null,
            {
                installTemplateSuccess: () => null,
                installTemplate: (_, { name }) => name,
            },
        ],
        templatesList: [
            [] as LemonSelectOption<string>[],
            {
                loadRepositorySuccess: (_, { repository }) => {
                    return Object.values(repository)
                        .filter((r) => !!r.installed)
                        .map((entry) => ({
                            value: entry.name,
                            label: entry.name,
                            'data-attr': `dashboard-select-${entry.name.replace(' ', '-')}`,
                        }))
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        installTemplateSuccess: () => actions.loadRepository(),
    })),
    selectors({
        isUsingDashboardTemplates: [
            (s) => [s.featureFlags],
            (featureFlags) => {
                return featureFlags[FEATURE_FLAGS.DASHBOARD_TEMPLATES]
            },
        ],
        isUsingDashboardTemplatesV2: [
            (s) => [s.featureFlags],
            (featureFlags) => {
                return featureFlags[FEATURE_FLAGS.TEMPLUKES]
            },
        ],
    }),
    afterMount(({ actions, values }) => {
        if (values.isUsingDashboardTemplates) {
            actions.loadRepository()
        }
        if (values.isUsingDashboardTemplatesV2) {
            actions.getAllTemplates()
        }
    }),
])
