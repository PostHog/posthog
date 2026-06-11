import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconBolt, IconRefresh, IconSearch } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import {
    INBOX_PRIORITY_OPTIONS,
    INBOX_SORT_OPTIONS,
    INBOX_SOURCE_OPTIONS,
    inboxPriorityFilterLabel,
    inboxSortOptionKey,
    inboxSourceFilterLabel,
} from '../../filterOptions'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { SignalReportPriority } from '../../types'

/** A single filter trigger + dropdown overlay, matching desktop's `InboxFilterPopover`. */
function FilterPopover({
    label,
    value,
    icon,
    active,
    children,
}: {
    label: string
    value: string
    icon: JSX.Element
    active: boolean
    children: React.ReactNode
}): JSX.Element {
    const [visible, setVisible] = useState(false)
    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={visible}
            onVisibilityChange={setVisible}
            matchWidth={false}
            actionable
            overlay={<div className="min-w-[200px] max-w-[260px] p-1 space-y-px">{children}</div>}
        >
            <LemonButton
                type="secondary"
                size="small"
                icon={icon}
                className="bg-surface-primary"
                aria-label={`${label}: ${value}`}
                sideIcon={active ? <LemonBadge size="small" status="primary" /> : undefined}
            >
                <span className="max-w-[150px] truncate">{value}</span>
            </LemonButton>
        </LemonDropdown>
    )
}

interface InboxSearchFilterBarProps {
    searchPlaceholder?: string
    /** Triggers a reload of the report list (lives on `inboxSceneLogic`). */
    onRefresh?: () => void
    refreshing?: boolean
}

/**
 * Search input + Source / Sort / Priority filter popovers + refresh. One-to-one
 * port of desktop `InboxSearchFilterBar`. There is no status filter (desktop
 * dropped it; status is a fixed request constant). Filter state is persisted via
 * `inboxFiltersLogic`; the central scene reloads on change.
 */
export function InboxSearchFilterBar({
    searchPlaceholder = 'Search by title or description…',
    onRefresh,
    refreshing,
}: InboxSearchFilterBarProps): JSX.Element {
    const { searchQuery, sortField, sortDirection, sourceProductFilter, priorityFilter } = useValues(inboxFiltersLogic)
    const { setSearchQuery, setSort, toggleSourceProduct, togglePriority } = useActions(inboxFiltersLogic)

    const activeSort = INBOX_SORT_OPTIONS.find((o) => o.field === sortField && o.direction === sortDirection)
    const activeSortKey = inboxSortOptionKey(sortField, sortDirection)

    return (
        <div className="flex items-center gap-2 flex-wrap w-full">
            <LemonInput
                className="flex-1 min-w-[220px]"
                type="search"
                value={searchQuery}
                onChange={setSearchQuery}
                placeholder={searchPlaceholder}
                prefix={<IconSearch />}
                size="small"
            />

            <FilterPopover
                label="Source"
                value={inboxSourceFilterLabel(sourceProductFilter)}
                icon={INBOX_SOURCE_OPTIONS[0].icon}
                active={sourceProductFilter.length > 0}
            >
                {INBOX_SOURCE_OPTIONS.map((option) => (
                    <LemonButton
                        key={option.value}
                        fullWidth
                        size="small"
                        icon={option.icon}
                        active={sourceProductFilter.includes(option.value)}
                        onClick={() => toggleSourceProduct(option.value)}
                        className="justify-between"
                    >
                        {option.label}
                    </LemonButton>
                ))}
            </FilterPopover>

            <FilterPopover
                label="Sort"
                value={activeSort?.label ?? 'Priority first'}
                icon={INBOX_SORT_OPTIONS[0].icon}
                active={activeSortKey !== 'priority:asc'}
            >
                {INBOX_SORT_OPTIONS.map((option) => (
                    <LemonButton
                        key={inboxSortOptionKey(option.field, option.direction)}
                        fullWidth
                        size="small"
                        icon={option.icon}
                        active={sortField === option.field && sortDirection === option.direction}
                        onClick={() => setSort(option.field, option.direction)}
                        className="justify-between"
                    >
                        {option.label}
                    </LemonButton>
                ))}
            </FilterPopover>

            <FilterPopover
                label="Priority"
                value={inboxPriorityFilterLabel(priorityFilter)}
                icon={<IconBolt />}
                active={priorityFilter.length > 0}
            >
                {INBOX_PRIORITY_OPTIONS.map((option) => (
                    <LemonButton
                        key={option.value}
                        fullWidth
                        size="small"
                        active={priorityFilter.includes(option.value)}
                        onClick={() => togglePriority(option.value as SignalReportPriority)}
                        className="justify-between"
                    >
                        <span className="flex items-center gap-2">
                            <span
                                className="inline-block h-2 w-2 shrink-0 rounded-full"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ backgroundColor: option.accent }}
                            />
                            {option.value}
                        </span>
                    </LemonButton>
                ))}
            </FilterPopover>

            {onRefresh && (
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconRefresh />}
                    loading={refreshing}
                    tooltip="Refresh"
                    aria-label="Refresh"
                    onClick={onRefresh}
                    className="bg-surface-primary"
                />
            )}
        </div>
    )
}
