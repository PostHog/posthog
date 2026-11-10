import clsx from 'clsx'

import type { DashboardWidgetPlacementDestination } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import type { TileGroupDisplay } from '~/types'

import type { DashboardSection } from '../dashboardTileSections'
import { DashboardTileGroup } from './DashboardTileGroup/DashboardTileGroup'
import type { DashboardTileGroupMenuActions } from './DashboardTileGroup/DashboardTileGroupMenuOverlay'

interface DashboardTileSectionBandProps {
    section: DashboardSection
    isFirst: boolean
    isDropTarget: boolean
    collapsedTileGroupKeys: string[]
    onToggleTileGroup: (groupKey: string) => void
    onRenameTileGroup?: (groupKey: string, title: string) => void
    renamingTileGroupKey?: string | null
    onRenamingTileGroupKeyChange?: (groupKey: string | null) => void
    onRemoveTileGroup?: (groupKey: string) => void
    copyToDestinations?: DashboardWidgetPlacementDestination[]
    onCopyGroupToDashboard?: (groupKey: string, dashboardId: number, dashboardName: string) => void
    copyLoading?: boolean
    onChangeGroupDisplay?: (groupDisplay: TileGroupDisplay) => void
    getAddTileOptions?: (groupKey: string) => DashboardTileGroupMenuActions['addTileOptions']
    getEmptyGroupAddAction?: (groupKey: string) => React.ReactNode
    children: React.ReactNode
}

export function DashboardTileSectionBand({
    section,
    isFirst,
    isDropTarget,
    collapsedTileGroupKeys,
    onToggleTileGroup,
    onRenameTileGroup,
    renamingTileGroupKey,
    onRenamingTileGroupKeyChange,
    onRemoveTileGroup,
    copyToDestinations,
    onCopyGroupToDashboard,
    copyLoading,
    onChangeGroupDisplay,
    getAddTileOptions,
    getEmptyGroupAddAction,
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
                    onRename={onRenameTileGroup ? (title) => onRenameTileGroup(section.groupKey, title) : undefined}
                    renaming={renamingTileGroupKey === section.groupKey}
                    onRenamingChange={(renaming) => onRenamingTileGroupKeyChange?.(renaming ? section.groupKey : null)}
                    onRemove={onRemoveTileGroup ? () => onRemoveTileGroup(section.groupKey) : undefined}
                    copyToDestinations={copyToDestinations}
                    onCopyToDashboard={
                        onCopyGroupToDashboard && section.tiles.length > 0
                            ? (dashboardId, dashboardName) =>
                                  onCopyGroupToDashboard(section.groupKey, dashboardId, dashboardName)
                            : undefined
                    }
                    copyLoading={copyLoading}
                    onChangeGroupDisplay={onChangeGroupDisplay}
                    addTileOptions={getAddTileOptions?.(section.groupKey)}
                    emptyAddAction={getEmptyGroupAddAction?.(section.groupKey)}
                >
                    {children}
                </DashboardTileGroup>
            )}
        </div>
    )
}
