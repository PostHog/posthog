import { kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import posthog from 'lib/posthog-typed'

import type { DashboardActivitySummary } from '~/types'

import type { dashboardActivitySummaryLogicType } from './dashboardActivitySummaryLogicType'

export interface DashboardActivitySummaryLogicProps {
    dashboardId: number
}

export const dashboardActivitySummaryLogic = kea<dashboardActivitySummaryLogicType>([
    path((key) => ['scenes', 'dashboard', 'dashboardActivitySummaryLogic', key]),
    props({} as DashboardActivitySummaryLogicProps),
    key((props) => props.dashboardId),
    loaders(({ props }) => ({
        activitySummary: [
            null as DashboardActivitySummary | null,
            {
                loadActivitySummary: async () => {
                    posthog.capture('dashboard activity summary viewed', { dashboard_id: props.dashboardId })
                    return await api.dashboards.activitySummary(props.dashboardId)
                },
            },
        ],
    })),
])
