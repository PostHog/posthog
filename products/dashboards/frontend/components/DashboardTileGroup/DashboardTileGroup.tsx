import clsx from 'clsx'

import { IconChevronRight } from '@posthog/icons'

import type { DashboardWidgetPlacementDestination } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenu'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { pluralize } from 'lib/utils/strings'

import type { DashboardTileGroupApi } from '../../generated/api.schemas'
import { DashboardTileGroupCopyMenu } from './DashboardTileGroupCopyMenu'
import { TileGroupColorDot } from './TileGroupColorDot'

interface DashboardTileGroupProps {
    group: DashboardTileGroupApi
    tileCount: number
    collapsed: boolean
    onToggle: () => void
    copyToDestinations?: DashboardWidgetPlacementDestination[]
    onCopyToDashboard?: (dashboardId: number, dashboardName: string) => void
    copyLoading?: boolean
    children: React.ReactNode
}

export function DashboardTileGroup({
    group,
    tileCount,
    collapsed,
    onToggle,
    copyToDestinations,
    onCopyToDashboard,
    copyLoading,
    children,
}: DashboardTileGroupProps): JSX.Element {
    const tileCountLabel = pluralize(tileCount, 'tile')

    return (
        <section className="DashboardTileGroup" data-attr="dashboard-tile-group">
            <div className="flex min-w-0 items-center gap-2 pb-2">
                <LemonButton
                    size="small"
                    truncate
                    // A tertiary button styles aria-expanded as an open menu, which reads as a highlight here.
                    className="[&[aria-expanded=true]:not(:hover)]:!bg-transparent"
                    tooltip={group.title || undefined}
                    icon={
                        <IconChevronRight
                            className={clsx(
                                'transition-transform motion-reduce:transition-none',
                                !collapsed && 'rotate-90'
                            )}
                        />
                    }
                    onClick={onToggle}
                    aria-expanded={!collapsed}
                    data-attr="dashboard-tile-group-toggle"
                >
                    {group.color && <TileGroupColorDot color={group.color} className="mr-2" />}
                    <span className="font-semibold">{group.title || tileCountLabel}</span>
                </LemonButton>
                {group.title && collapsed && <span className="shrink-0 text-secondary text-xs">{tileCountLabel}</span>}
                <div className="min-w-4 flex-1 border-t border-primary" />
                {onCopyToDashboard && (
                    <DashboardTileGroupCopyMenu
                        label="Copy group to dashboard"
                        destinations={copyToDestinations ?? []}
                        onCopyToDashboard={onCopyToDashboard}
                        loading={copyLoading}
                    />
                )}
            </div>
            {!collapsed && children}
        </section>
    )
}
