import { actions, afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { DashboardTemplateType } from '~/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

import type { dashboardTemplatesLogicType } from './dashboardTemplatesLogicType'

export const dashboardTemplatesLogic = kea<dashboardTemplatesLogicType>([
    path(['scenes', 'dashboard', 'dashboards', 'templates', 'dashboardTemplatesLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),
    actions({
        setTemplates: (allTemplates: DashboardTemplateType[]) => ({ allTemplates }),
    }),
    loaders({
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
    selectors({
        isUsingDashboardTemplatesV2: [
            (s) => [s.featureFlags],
            (featureFlags) => {
                return featureFlags[FEATURE_FLAGS.TEMPLUKES]
            },
        ],
    }),
    afterMount(({ actions, values }) => {
        if (values.isUsingDashboardTemplatesV2) {
            actions.getAllTemplates()
        }
    }),
])
