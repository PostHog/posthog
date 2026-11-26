import { useActions, useValues } from 'kea'

import { urls } from 'scenes/urls'

import { dashboardResultFilterLogic } from '../dashboardResultFilterLogic'
import { DashboardSelectionFilterBar } from './DashboardSelectionFilterBar'

export function DashboardResultFilterBar({ dashboardId }: { dashboardId: number }): JSX.Element | null {
    const { selection, targets, sourceInsight } = useValues(dashboardResultFilterLogic({ dashboardId }))
    const { setSelection } = useActions(dashboardResultFilterLogic({ dashboardId }))
    return selection ? (
        <DashboardSelectionFilterBar
            type="insight"
            summary={selection.label}
            sourceTitle={sourceInsight?.name || 'Untitled insight'}
            sourceInsightUrl={sourceInsight ? urls.insightView(sourceInsight.short_id) : undefined}
            targetCount={Object.keys(targets).length}
            onClear={() => setSelection(null)}
        />
    ) : null
}
