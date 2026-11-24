import api from 'lib/api'

import { DashboardType } from '~/types'

export const DASHBOARD_TAG = 'llm-analytics'

// The tab creates its default dashboard unlisted, and the list leaves unlisted dashboards out unless asked.
export async function listAIObservabilityDashboards(): Promise<DashboardType[]> {
    const response = await api.dashboards.list({ tags: DASHBOARD_TAG, creation_mode: 'unlisted' })
    return response.results || []
}

/** The dashboard the tab opens when the person has not picked one. Never creates it. */
export async function findAIObservabilityDashboardId(): Promise<number | null> {
    const [first] = await listAIObservabilityDashboards()
    return first?.id ?? null
}
