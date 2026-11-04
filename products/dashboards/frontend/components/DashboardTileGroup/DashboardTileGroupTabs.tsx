import type { DashboardWidgetPlacementDestination } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { TileGroupDisplay } from '~/types'

import { type DashboardSection, getTileGroupLabel } from '../../dashboardTileSections'
import { DashboardTileGroupContextMenu } from './DashboardTileGroupContextMenu'
import { DashboardTileGroupEmptyTab } from './DashboardTileGroupEmptyTab'
import { DashboardTileGroupMenu } from './DashboardTileGroupMenu'
import { type DashboardTileGroupMenuActions, hasTileGroupMenuActions } from './DashboardTileGroupMenuOverlay'
import { DashboardTileGroupTitleInput } from './DashboardTileGroupTitleInput'
import { TileGroupColorDot } from './TileGroupColorDot'

interface DashboardTileGroupTabsProps {
    sections: DashboardSection[]
    activeSectionKey: string
    onSelect: (sectionKey: string) => void
    onRenameGroup?: (groupKey: string, title: string) => void
    renamingGroupKey?: string | null
    onRenamingGroupKeyChange?: (groupKey: string | null) => void
    onRemoveGroup?: (groupKey: string) => void
    copyToDestinations?: DashboardWidgetPlacementDestination[]
    onCopyGroupToDashboard?: (groupKey: string, dashboardId: number, dashboardName: string) => void
    copyLoading?: boolean
    onChangeGroupDisplay?: (groupDisplay: TileGroupDisplay) => void
    getAddTileOptions?: (groupKey: string) => DashboardTileGroupMenuActions['addTileOptions']
    getEmptyGroupAddAction?: (groupKey: string) => React.ReactNode
    children: React.ReactNode
}

export function DashboardTileGroupTabs({
    sections,
    activeSectionKey,
    onSelect,
    onRenameGroup,
    renamingGroupKey = null,
    onRenamingGroupKeyChange,
    onRemoveGroup,
    copyToDestinations,
    onCopyGroupToDashboard,
    copyLoading,
    onChangeGroupDisplay,
    getEmptyGroupAddAction,
    getAddTileOptions,
    children,
}: DashboardTileGroupTabsProps): JSX.Element {
    const activeSection = sections.find((section) => section.key === activeSectionKey)

    const getMenuActions = (section: DashboardSection | undefined): DashboardTileGroupMenuActions => {
        if (section?.kind !== 'group') {
            return { groupDisplay: 'tabs', onChangeGroupDisplay }
        }
        const { groupKey } = section
        return {
            groupDisplay: 'tabs',
            addTileOptions: getAddTileOptions?.(groupKey),
            onStartRename:
                onRenameGroup && onRenamingGroupKeyChange ? () => onRenamingGroupKeyChange(groupKey) : undefined,
            onRemove: onRemoveGroup ? () => onRemoveGroup(groupKey) : undefined,
            groupHasTiles: section.tiles.length > 0,
            onChangeGroupDisplay,
            copyToDestinations,
            onCopyToDashboard:
                section.tiles.length > 0 && onCopyGroupToDashboard
                    ? (dashboardId, dashboardName) => onCopyGroupToDashboard(groupKey, dashboardId, dashboardName)
                    : undefined,
        }
    }

    const activeMenuActions = getMenuActions(activeSection)

    return (
        <section data-attr="dashboard-tile-group-tabs">
            <LemonTabs
                activeKey={activeSectionKey}
                onChange={onSelect}
                tabs={sections.map((section) => ({
                    key: section.key,
                    label:
                        section.kind === 'group' && section.groupKey === renamingGroupKey && onRenameGroup ? (
                            <DashboardTileGroupTitleInput
                                initialTitle={section.group.title ?? ''}
                                placeholder={getTileGroupLabel({}, section.tiles.length)}
                                onSave={(title) => onRenameGroup(section.groupKey, title)}
                                onDone={() => onRenamingGroupKeyChange?.(null)}
                            />
                        ) : section.kind === 'group' ? (
                            <DashboardTileGroupContextMenu
                                className="flex items-center gap-2"
                                onDoubleClick={
                                    onRenameGroup && onRenamingGroupKeyChange
                                        ? () => onRenamingGroupKeyChange(section.groupKey)
                                        : undefined
                                }
                                {...getMenuActions(section)}
                            >
                                {section.group.color && <TileGroupColorDot color={section.group.color} />}
                                {/* Long titles cut off so one tab can't push the others out of the bar. */}
                                <Tooltip title={section.group.title || undefined}>
                                    <span className="max-w-50 truncate">
                                        {getTileGroupLabel(section.group, section.tiles.length)}
                                    </span>
                                </Tooltip>
                            </DashboardTileGroupContextMenu>
                        ) : (
                            'Overview'
                        ),
                }))}
                rightSlotClassName="pr-0"
                trackTabSizes
                rightSlot={
                    hasTileGroupMenuActions(activeMenuActions) && (
                        <DashboardTileGroupMenu {...activeMenuActions} copyLoading={copyLoading} />
                    )
                }
            />
            {activeSection?.kind === 'group' && activeSection.tiles.length === 0 ? (
                <DashboardTileGroupEmptyTab
                    addAction={getEmptyGroupAddAction?.(activeSection.groupKey)}
                    onRemove={activeMenuActions.onRemove}
                />
            ) : (
                children
            )}
        </section>
    )
}
