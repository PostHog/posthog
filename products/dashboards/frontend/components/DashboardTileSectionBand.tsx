import clsx from 'clsx'

import type { DashboardWidgetPlacementDestination } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import type { DashboardSection } from '../dashboardTileSections'
import { DashboardTileGroup } from './DashboardTileGroup/DashboardTileGroup'

interface DashboardTileSectionBandProps {
    section: DashboardSection
    isFirst: boolean
    isDropTarget: boolean
    collapsedTileGroupKeys: string[]
    onToggleTileGroup: (groupKey: string) => void
    copyToDestinations?: DashboardWidgetPlacementDestination[]
    onCopyGroupToDashboard?: (groupKey: string, dashboardId: number, dashboardName: string) => void
    copyLoading?: boolean
    children: React.ReactNode
}

export function DashboardTileSectionBand({
    section,
    isFirst,
    isDropTarget,
    collapsedTileGroupKeys,
    onToggleTileGroup,
    copyToDestinations,
    onCopyGroupToDashboard,
    copyLoading,
    children,
}: DashboardTileSectionBandProps): JSX.Element {
    return (
        <div data-dashboard-section={section.key} className={clsx('rounded-lg', isDropTarget && 'ring-2 ring-accent')}>
            {section.kind === 'tiles' ? (
                <>
                    {/* Without a line, viewers read loose tiles under a closed group as part of that group. */}
                    {!isFirst && <LemonDivider className="mb-4" />}
                    {children}
                </>
            ) : (
                <DashboardTileGroup
                    group={section.group}
                    tileCount={section.tiles.length}
                    collapsed={collapsedTileGroupKeys.includes(section.groupKey)}
                    onToggle={() => onToggleTileGroup(section.groupKey)}
                    copyToDestinations={copyToDestinations}
                    onCopyToDashboard={
                        onCopyGroupToDashboard
                            ? (dashboardId, dashboardName) =>
                                  onCopyGroupToDashboard(section.groupKey, dashboardId, dashboardName)
                            : undefined
                    }
                    copyLoading={copyLoading}
                >
                    {children}
                </DashboardTileGroup>
            )}
        </div>
    )
}
