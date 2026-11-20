import { ReactNode } from 'react'

import { IconCopy, IconFilter } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'

export type OverviewFilterState = 'active' | 'replace' | 'inactive'

function WithTooltip({ tooltip, children }: { tooltip: ReactNode; children: JSX.Element }): JSX.Element {
    if (!tooltip) {
        return children
    }
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="contents" />}>{children}</TooltipTrigger>
            <TooltipContent className="max-w-80">{tooltip}</TooltipContent>
        </Tooltip>
    )
}

/** One label and value line of the overview tables, with optional copy and filter actions on the value. */
export function QuillOverviewRow({
    label,
    icon,
    keyTooltip,
    valueTooltip,
    copyValue,
    filterState,
    filterDisabledReason,
    onFilterClick,
    children,
}: {
    label: ReactNode
    icon?: ReactNode
    keyTooltip?: ReactNode
    valueTooltip?: ReactNode
    copyValue?: string
    /** Set to show the filter button; `onFilterClick` is absent when the value cannot be filtered. */
    filterState?: OverviewFilterState
    filterDisabledReason?: string
    onFilterClick?: () => void
    children: ReactNode
}): JSX.Element {
    const filterTooltip = filterDisabledReason
        ? filterDisabledReason
        : filterState === 'active'
          ? 'Remove this filter'
          : filterState === 'replace'
            ? 'Replace existing filter with this value'
            : 'Filter for recordings matching this'
    return (
        <div className="group flex w-full items-center justify-between gap-4 px-2 py-1">
            <WithTooltip tooltip={keyTooltip}>
                <span className="flex items-center gap-1 text-sm shrink-0 truncate max-w-[60%] font-light">
                    {icon}
                    {label}
                </span>
            </WithTooltip>
            <div className="flex items-center gap-1 min-w-0">
                <WithTooltip tooltip={valueTooltip}>
                    <span className="truncate min-w-0">{children}</span>
                </WithTooltip>
                {copyValue !== undefined && (
                    <Button
                        size="icon-xs"
                        tooltip="Copy value"
                        aria-label="Copy value"
                        onClick={() => void copyToClipboard(copyValue, typeof label === 'string' ? label : 'value')}
                        data-attr="player-overview-copy-property-value"
                    >
                        <IconCopy />
                    </Button>
                )}
                {filterState && (
                    <Button
                        size="icon-xs"
                        variant={filterState === 'active' && !filterDisabledReason ? 'secondary' : 'default'}
                        className={cn(
                            filterState !== 'active' &&
                                'text-muted-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100'
                        )}
                        tooltip={filterTooltip}
                        aria-label={filterTooltip}
                        disabledReason={filterDisabledReason}
                        onClick={onFilterClick}
                        data-testid="filter-button"
                    >
                        <IconFilter />
                    </Button>
                )}
            </div>
        </div>
    )
}
