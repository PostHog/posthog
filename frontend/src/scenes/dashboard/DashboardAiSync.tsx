import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import { DASHBOARD_AI_MUTATION_TOOLS, dashboardAiSyncLogic } from './dashboardAiSyncLogic'

interface DashboardAiSyncProps {
    dashboardId: number
    onTransientHighlightedTileIdsChange?: (tileIds: number[]) => void
}

export function DashboardAiSync({ dashboardId, onTransientHighlightedTileIdsChange }: DashboardAiSyncProps): null {
    const { applyToolCompletion } = useActions(dashboardAiSyncLogic({ dashboardId }))
    const { transientHighlightedTileIds } = useValues(dashboardAiSyncLogic({ dashboardId }))

    useEffect(() => {
        onTransientHighlightedTileIdsChange?.(transientHighlightedTileIds)
    }, [onTransientHighlightedTileIdsChange, transientHighlightedTileIds])

    useEffect(
        () => () => {
            onTransientHighlightedTileIdsChange?.([])
        },
        [onTransientHighlightedTileIdsChange]
    )

    useMcpToolApplyBack({
        tools: [...DASHBOARD_AI_MUTATION_TOOLS],
        targetKey: `dashboard:${dashboardId}`,
        applyOn: 'tool_call_completed',
        active: true,
        onApply: (event, { innerInput }) => applyToolCompletion(event, innerInput),
    })

    return null
}
