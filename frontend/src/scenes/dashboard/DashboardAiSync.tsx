import { useActions, useValues } from 'kea'

import { sceneAgentPanelLogic } from 'scenes/max/sceneAgentPanelLogic'

import { useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import { DASHBOARD_AI_MUTATION_TOOLS, dashboardAiSyncLogic } from './dashboardAiSyncLogic'

export function DashboardAiSync({ dashboardId }: { dashboardId: number }): null {
    const { applyToolCompletion } = useActions(dashboardAiSyncLogic({ dashboardId }))
    const { sceneIntegrationEnabled } = useValues(sceneAgentPanelLogic)

    useMcpToolApplyBack({
        tools: [...DASHBOARD_AI_MUTATION_TOOLS],
        targetKey: `dashboard:${dashboardId}`,
        applyOn: 'tool_call_completed',
        active: sceneIntegrationEnabled,
        onApply: (event, { innerInput }) => applyToolCompletion(event, innerInput),
    })

    return null
}
