import clsx from 'clsx'

import { IconChevronRight } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { pluralize } from 'lib/utils/strings'

import type { DashboardTileGroupApi, DashboardTileGroupRailEnumApi } from '../../generated/api.schemas'

const RAIL_CLASS_NAMES: Record<DashboardTileGroupRailEnumApi, string> = {
    blue: 'border-l-[var(--blue)]',
    purple: 'border-l-[var(--purple)]',
    green: 'border-l-[var(--green)]',
    yellow: 'border-l-[var(--warning)]',
    orange: 'border-l-[var(--color-orange-500)]',
    red: 'border-l-[var(--danger)]',
}

// The horizontal inset is in pixels, not rem, so that the dashboard can give the group's grid an exact width.
const RAIL_WIDTH = 4
const PADDING = 8

export function getTileGroupContentWidth(group: DashboardTileGroupApi, width: number): number {
    const tinted = group.tint ?? true
    const left = group.rail ? RAIL_WIDTH + PADDING : tinted ? PADDING : 0
    const right = tinted ? PADDING : 0
    return width - left - right
}

interface DashboardTileGroupProps {
    group: DashboardTileGroupApi
    tileCount: number
    collapsed: boolean
    onToggle: () => void
    children: React.ReactNode
}

export function DashboardTileGroup({
    group,
    tileCount,
    collapsed,
    onToggle,
    children,
}: DashboardTileGroupProps): JSX.Element {
    const tileCountLabel = pluralize(tileCount, 'tile')
    const tinted = group.tint ?? true

    return (
        <section
            className={clsx(
                'DashboardTileGroup rounded-lg',
                tinted && 'bg-fill-secondary px-[8px] pb-2',
                group.rail && ['border-l-4 pl-[8px]', RAIL_CLASS_NAMES[group.rail]]
            )}
            data-attr="dashboard-tile-group"
        >
            <div className="flex min-w-0 items-center gap-2 pt-1 pb-2">
                <LemonButton
                    size="small"
                    truncate
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
                    <span className="font-semibold">{group.title || tileCountLabel}</span>
                </LemonButton>
                {group.title && <span className="shrink-0 text-secondary text-xs">{tileCountLabel}</span>}
            </div>
            {!collapsed && children}
        </section>
    )
}
