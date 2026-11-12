import type { InsightCardMenuPlacement } from './insightCardMenu'
import { QuillDashboardWidgetPlacementMenu } from './QuillDashboardWidgetPlacementMenu'

export function QuillDashboardWidgetPlacementMenus({
    destinations,
    onMoveToDashboard,
    onCopyToDashboard,
    tileGroupMoveOptions,
    onMoveToTileGroup,
}: InsightCardMenuPlacement): JSX.Element {
    return (
        <>
            {onMoveToDashboard && (
                <QuillDashboardWidgetPlacementMenu
                    label="Move to"
                    destinations={destinations}
                    onSelect={(dashboard) => onMoveToDashboard({ id: dashboard.id, name: dashboard.name })}
                    emptyDisabledReason="No dashboards you can move to"
                    tileGroupMoveOptions={tileGroupMoveOptions}
                    onMoveToTileGroup={onMoveToTileGroup}
                />
            )}
            {onCopyToDashboard && (
                <QuillDashboardWidgetPlacementMenu
                    label="Copy to"
                    destinations={destinations}
                    onSelect={onCopyToDashboard}
                    emptyDisabledReason="No dashboards you can copy to"
                />
            )}
        </>
    )
}
