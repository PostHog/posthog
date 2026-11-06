import { useActions } from 'kea'

import { todayAnalyticsLogic } from '~/layout/today/todayAnalyticsLogic'

import { useToolStreamListener } from 'products/posthog_ai/frontend/api/logics'

/** Reloads the Analytics sidebar when PostHog AI changes it, so the new layout shows as soon as the agent saves it. */
export function AnalyticsSidebarAgentListener(): null {
    const { loadSidebar } = useActions(todayAnalyticsLogic)
    useToolStreamListener({
        tools: ['today-analytics-sidebar-update', 'today-analytics-sidebar-reset'],
        onEvent: (event) => {
            if (event.phase === 'completed') {
                loadSidebar()
            }
        },
    })
    return null
}
