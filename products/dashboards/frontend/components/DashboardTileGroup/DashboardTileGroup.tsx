import clsx from 'clsx'

import { IconChevronRight } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { pluralize } from 'lib/utils/strings'

import type { DashboardTileGroupApi, DashboardTileGroupColorEnumApi } from '../../generated/api.schemas'

const DOT_CLASS_NAMES: Record<DashboardTileGroupColorEnumApi, string> = {
    blue: 'bg-[var(--blue)]',
    purple: 'bg-[var(--purple)]',
    green: 'bg-[var(--green)]',
    yellow: 'bg-[var(--warning)]',
    orange: 'bg-[var(--color-orange-500)]',
    red: 'bg-[var(--danger)]',
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
                    {group.color && (
                        <span
                            aria-hidden
                            className={clsx('mr-2 inline-block size-2 rounded-full', DOT_CLASS_NAMES[group.color])}
                        />
                    )}
                    <span className="font-semibold">{group.title || tileCountLabel}</span>
                </LemonButton>
                {group.title && collapsed && <span className="shrink-0 text-secondary text-xs">{tileCountLabel}</span>}
                <div className="min-w-4 flex-1 border-t border-primary" />
            </div>
            {!collapsed && children}
        </section>
    )
}
