import { useActions, useValues } from 'kea'

import { useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import { DASHBOARD_AI_TOOL_NAMES, dashboardAiSyncLogic, snapshotDashboardTiles } from './dashboardAiSyncLogic'
import { dashboardLogic } from './dashboardLogic'

export interface DashboardAiSyncProps {
    dashboardId: number
}

export function DashboardAiSync({ dashboardId }: DashboardAiSyncProps): null {
    const { tiles } = useValues(dashboardLogic)
    const { agentToolCompleted } = useActions(dashboardAiSyncLogic({ dashboardId }))

    useMcpToolApplyBack({
        tools: [...DASHBOARD_AI_TOOL_NAMES],
        targetKey: 'dashboard:' + dashboardId,
        active: true,
        applyOn: 'tool_call_completed',
        onApply: (event, { innerInput }) => {
            agentToolCompleted(event.toolName, innerInput, snapshotDashboardTiles(tiles))
        },
    })

    return null
}
