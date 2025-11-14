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
    filterState,
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
    filterState?: 'active' | 'replace' | 'inactive'
}): JSX.Element {
    const getFilterTooltip = (): string => {
        if (filterDisabledReason) {
            return filterDisabledReason
        }
        if (filterState === 'active') {
            return 'Remove this filter'
        }
        if (filterState === 'replace') {
            return 'Replace existing filter with this value'
        }
        return 'Filter for recordings matching this'
    }

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
                    <Tooltip title={getFilterTooltip()}>
                        <IconFilter
                            data-testid="filter-button"
                            className={clsx(
                                'text-sm transition-colors',
                                filterDisabledReason
                                    ? 'text-muted cursor-not-allowed'
                                    : filterState === 'active'
                                      ? 'cursor-pointer text-primary hover:text-secondary'
                                      : 'cursor-pointer text-secondary hover:text-primary'
                            )}
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
