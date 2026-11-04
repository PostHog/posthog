import type { DashboardWidgetPlacementDestination } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import type { TileGroupDisplay } from '~/types'

import { type DashboardSection, getTileGroupLabel } from '../../dashboardTileSections'
import { DashboardTileGroupMenu } from './DashboardTileGroupMenu'
import { TileGroupColorDot } from './TileGroupColorDot'

interface DashboardTileGroupTabsProps {
    sections: DashboardSection[]
    activeSectionKey: string
    onSelect: (sectionKey: string) => void
    onRenameGroup?: (groupKey: string, title: string) => void
    copyToDestinations?: DashboardWidgetPlacementDestination[]
    onCopyGroupToDashboard?: (groupKey: string, dashboardId: number, dashboardName: string) => void
    copyLoading?: boolean
    onChangeGroupDisplay?: (groupDisplay: TileGroupDisplay) => void
    children: React.ReactNode
}

export function DashboardTileGroupTabs({
    sections,
    activeSectionKey,
    onSelect,
    onRenameGroup,
    copyToDestinations,
    onCopyGroupToDashboard,
    copyLoading,
    onChangeGroupDisplay,
    children,
}: DashboardTileGroupTabsProps): JSX.Element {
    const activeSection = sections.find((section) => section.key === activeSectionKey)

    return (
        <section data-attr="dashboard-tile-group-tabs">
            <LemonTabs
                activeKey={activeSectionKey}
                onChange={onSelect}
                tabs={sections.map((section) => ({
                    key: section.key,
                    label:
                        section.kind === 'group' ? (
                            <span className="flex items-center gap-2">
                                {section.group.color && <TileGroupColorDot color={section.group.color} />}
                                {getTileGroupLabel(section.group, section.tiles.length)}
                            </span>
                        ) : (
                            'Overview'
                        ),
                }))}
                rightSlotClassName="pr-0"
                rightSlot={
                    (onRenameGroup || onChangeGroupDisplay || onCopyGroupToDashboard) && (
                        <DashboardTileGroupMenu
                            groupDisplay="tabs"
                            title={activeSection?.kind === 'group' ? activeSection.group.title : undefined}
                            onRename={
                                activeSection?.kind === 'group' && onRenameGroup
                                    ? (title) => onRenameGroup(activeSection.groupKey, title)
                                    : undefined
                            }
                            onChangeGroupDisplay={onChangeGroupDisplay}
                            copyToDestinations={copyToDestinations}
                            onCopyToDashboard={
                                activeSection?.kind === 'group' && onCopyGroupToDashboard
                                    ? (dashboardId, dashboardName) =>
                                          onCopyGroupToDashboard(activeSection.groupKey, dashboardId, dashboardName)
                                    : undefined
                            }
                            copyLoading={copyLoading}
                        />
                    )
                }
            />
            {children}
        </section>
    )
}
