import clsx from 'clsx'
import { ReactNode } from 'react'

import { IconFilter } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

interface OverviewItemBase {
    icon?: ReactNode
    label: string
    valueTooltip?: ReactNode
    keyTooltip?: ReactNode
}

type TextOverviewItem = OverviewItemBase & {
    type: 'text'
    value: ReactNode
}

type PropertyOverviewItem = OverviewItemBase & {
    type: 'property'
    property: string
    value?: string | undefined
}

export type OverviewItem = TextOverviewItem | PropertyOverviewItem

export function OverviewGrid({ children }: { children: ReactNode }): JSX.Element {
    return (
        <div className="@container/og">
            <div className="grid grid-cols-1 place-items-center gap-4 px-2 py-1 @md/og:grid-cols-2 @2xl/og:grid-cols-3">
                {children}
            </div>
        </div>
    )
}

export function OverviewGridItem({
    children,
    description,
    label,
    icon,
    fadeLabel,
    itemKeyTooltip,
    onFilterClick,
    showFilter,
    filterDisabledReason,
}: {
    children?: ReactNode
    description: ReactNode
    label: ReactNode
    icon?: ReactNode
    fadeLabel?: boolean
    itemKeyTooltip?: ReactNode
    onFilterClick?: () => void
    showFilter?: boolean
    filterDisabledReason?: string
}): JSX.Element {
    return (
        <div className="group flex flex-1 w-full justify-between items-center deprecated-space-x-4">
            <div className={clsx('text-sm', fadeLabel && 'font-light')}>
                <Tooltip title={itemKeyTooltip}>
                    {icon} {label}
                </Tooltip>
            </div>
            <div className="overflow-x-auto flex items-center deprecated-space-x-2">
                <Tooltip title={description}>{children}</Tooltip>
                {showFilter && onFilterClick && (
                    <Tooltip title={filterDisabledReason || 'Filter for recordings matching this'}>
                        <IconFilter
                            data-testid="filter-button"
                            className={
                                filterDisabledReason
                                    ? 'text-muted cursor-not-allowed text-sm'
                                    : 'cursor-pointer text-secondary hover:text-primary transition-colors text-sm'
                            }
                            onClick={(e) => {
                                e.stopPropagation()
                                if (!filterDisabledReason) {
                                    onFilterClick()
                                }
                            }}
                        />
                    </Tooltip>
                )}
            </div>
        </div>
    )
}
