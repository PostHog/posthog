import clsx from 'clsx'

import { IconChevronRight } from '@posthog/icons'

import type { DashboardWidgetPlacementDestination } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { pluralize } from 'lib/utils/strings'

import type { TileGroupDisplay } from '~/types'

import type { DashboardTileGroupApi } from '../../generated/api.schemas'
import { DashboardTileGroupContextMenu } from './DashboardTileGroupContextMenu'
import { DashboardTileGroupMenu } from './DashboardTileGroupMenu'
import { type DashboardTileGroupMenuActions, hasTileGroupMenuActions } from './DashboardTileGroupMenuOverlay'
import { DashboardTileGroupTitleInput } from './DashboardTileGroupTitleInput'
import { TileGroupColorDot } from './TileGroupColorDot'

interface DashboardTileGroupProps {
    group: DashboardTileGroupApi
    tileCount: number
    collapsed: boolean
    onToggle: () => void
    addTileOptions?: DashboardTileGroupMenuActions['addTileOptions']
    emptyAddAction?: React.ReactNode
    onRename?: (title: string) => void
    renaming?: boolean
    onRenamingChange?: (renaming: boolean) => void
    onRemove?: () => void
    copyToDestinations?: DashboardWidgetPlacementDestination[]
    onCopyToDashboard?: (dashboardId: number, dashboardName: string) => void
    copyLoading?: boolean
    onChangeGroupDisplay?: (groupDisplay: TileGroupDisplay) => void
    children: React.ReactNode
}

export function DashboardTileGroup({
    group,
    tileCount,
    collapsed,
    onToggle,
    addTileOptions,
    emptyAddAction,
    onRename,
    renaming = false,
    onRenamingChange,
    onRemove,
    copyToDestinations,
    onCopyToDashboard,
    copyLoading,
    onChangeGroupDisplay,
    children,
}: DashboardTileGroupProps): JSX.Element {
    const tileCountLabel = pluralize(tileCount, 'tile')
    const menuActions: DashboardTileGroupMenuActions = {
        groupDisplay: 'sections',
        addTileOptions,
        onStartRename: onRename && onRenamingChange ? () => onRenamingChange(true) : undefined,
        onRemove,
        groupHasTiles: tileCount > 0,
        onChangeGroupDisplay,
        copyToDestinations,
        onCopyToDashboard,
    }

    return (
        <section className="DashboardTileGroup" data-attr="dashboard-tile-group">
            <div className="flex min-w-0 items-center gap-2 pb-2">
                <DashboardTileGroupContextMenu className="flex min-w-0" {...menuActions}>
                    <LemonButton
                        size="small"
                        truncate
                        // A tertiary button styles aria-expanded as an open menu, which reads as a highlight here.
                        className="[&[aria-expanded=true]:not(:hover)]:!bg-transparent"
                        tooltip={renaming ? undefined : group.title || undefined}
                        icon={
                            <IconChevronRight
                                className={clsx(
                                    'transition-transform motion-reduce:transition-none',
                                    !collapsed && 'rotate-90'
                                )}
                            />
                        }
                        onClick={renaming ? undefined : onToggle}
                        // The right-click menu wraps this button, which would otherwise add a dropdown arrow.
                        sideIcon={null}
                        aria-expanded={!collapsed}
                        data-attr="dashboard-tile-group-toggle"
                    >
                        {group.color && <TileGroupColorDot color={group.color} className="mr-2" />}
                        {renaming && onRename ? (
                            // Inside the button, so the chevron and padding stay where they are.
                            <DashboardTileGroupTitleInput
                                className="font-semibold"
                                initialTitle={group.title ?? ''}
                                placeholder={tileCountLabel}
                                onSave={onRename}
                                onDone={() => onRenamingChange?.(false)}
                            />
                        ) : (
                            <span className="font-semibold">{group.title || tileCountLabel}</span>
                        )}
                    </LemonButton>
                </DashboardTileGroupContextMenu>
                {group.title && collapsed && <span className="shrink-0 text-secondary text-xs">{tileCountLabel}</span>}
                <div className="min-w-4 flex-1 border-t border-primary" />
                {hasTileGroupMenuActions(menuActions) && (
                    <DashboardTileGroupMenu {...menuActions} copyLoading={copyLoading} />
                )}
            </div>
            {!collapsed && tileCount === 0 && (
                <div
                    className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-4 py-6 text-center text-secondary"
                    data-attr="dashboard-tile-group-empty"
                >
                    No tiles in this group yet. Add one, or move one here with its Move to option.
                    {(emptyAddAction || onRemove) && (
                        <div className="flex flex-wrap justify-center gap-2">
                            {emptyAddAction}
                            {onRemove && (
                                <LemonButton
                                    type="secondary"
                                    status="danger"
                                    size="small"
                                    onClick={onRemove}
                                    data-attr="dashboard-tile-group-empty-remove"
                                >
                                    Delete group
                                </LemonButton>
                            )}
                        </div>
                    )}
                </div>
            )}
            {!collapsed && children}
        </section>
    )
}
