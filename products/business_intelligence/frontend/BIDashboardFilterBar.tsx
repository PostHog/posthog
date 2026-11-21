import { useActions, useValues } from 'kea'

import { DashboardSelectionFilterBar } from 'products/dashboards/frontend/components/DashboardSelectionFilterBar'

import { biDashboardCrossFilterLogic } from './biDashboardCrossFilterLogic'

export function BIDashboardFilterBar({ dashboardId }: { dashboardId: number }): JSX.Element | null {
    const { selection, targets, sourceInsightUrl } = useValues(biDashboardCrossFilterLogic({ dashboardId }))
    const { setSelection } = useActions(biDashboardCrossFilterLogic({ dashboardId }))
    return selection ? (
        <DashboardSelectionFilterBar
            type="bi"
            summary={selection.selection.labels.map(({ name, value }) => `${name}: ${value}`).join(', ')}
            sourceTitle={selection.title}
            sourceInsightUrl={sourceInsightUrl}
            targetCount={Object.keys(targets).length}
            onClear={() => setSelection(null)}
        />
    ) : null
}
