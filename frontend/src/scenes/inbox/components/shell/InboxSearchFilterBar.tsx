import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconChevronDown, IconFlag, IconRefresh, IconSearch, IconSort, IconTarget } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import {
    INBOX_PRIORITY_OPTIONS,
    INBOX_SORT_OPTIONS,
    INBOX_SOURCE_OPTIONS,
    PRIORITY_ACCENT,
    PRIORITY_MEANING,
    inboxPriorityFilterLabel,
    inboxSortOptionKey,
    inboxSourceFilterLabel,
} from '../../filterOptions'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'

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
            placement="bottom-start"
            overlay={<div className="min-w-[200px] max-w-[260px] p-1 deprecated-space-y-px">{children}</div>}
        >
            <button
                type="button"
                aria-label={`${label}: ${value}`}
                // Quiet at rest: an unused filter is a muted, borderless chip showing its category
                // (e.g. "Source"). Once active it gains a solid border and its selected value — so
                // the bar only draws attention to filters actually in use.
                className={`flex h-8 shrink-0 items-center gap-1.5 rounded border px-2.5 text-sm transition-colors ${
                    active
                        ? 'border-primary bg-surface-primary text-default hover:border-secondary hover:bg-surface-secondary'
                        : 'border-transparent text-muted hover:border-primary hover:bg-surface-secondary hover:text-default'
                }`}
            >
                <span className="flex shrink-0 items-center text-tertiary [&>svg]:size-3.5">{icon}</span>
                <span className="max-w-[150px] truncate">{active ? value : label}</span>
                <IconChevronDown className="shrink-0 text-sm text-tertiary" />
            </button>
        </LemonDropdown>
    )
}

/** A single multi-select row inside a filter popover: icon/glyph + label, with a check when active. */
function FilterItem({
    icon,
    label,
    active,
    onClick,
}: {
    icon?: JSX.Element
    label: React.ReactNode
    active: boolean
    onClick: () => void
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            className="flex w-full items-center justify-between gap-2 rounded px-1.5 py-1 text-left text-sm text-default transition-colors hover:bg-surface-secondary"
        >
            <span className="flex min-w-0 items-center gap-1.5">
                {icon && <span className="flex shrink-0 items-center text-tertiary [&>svg]:size-3.5">{icon}</span>}
                <span className="truncate">{label}</span>
            </span>
            {active && <IconCheck className="shrink-0 text-sm text-default" />}
        </button>
    )
}

interface InboxSearchFilterBarProps {
    searchPlaceholder?: string
    /** Triggers a reload of the report list (lives on `inboxSceneLogic`). */
    onRefresh?: () => void
    refreshing?: boolean
}

/**
 * Search input + Sort / Source / Priority filter popovers + refresh. There is no
 * status filter (desktop dropped it; status is a fixed request constant). Each
 * popover stays a quiet, muted chip until its filter is in use, then gains a
 * solid border and shows its value. Filter state is persisted via
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
                label="Sort"
                value={activeSort?.label ?? 'Priority first'}
                icon={<IconSort />}
                active={activeSortKey !== 'priority:asc'}
            >
                {INBOX_SORT_OPTIONS.map((option) => (
                    <FilterItem
                        key={inboxSortOptionKey(option.field, option.direction)}
                        icon={option.icon}
                        label={option.label}
                        active={sortField === option.field && sortDirection === option.direction}
                        onClick={() => setSort(option.field, option.direction)}
                    />
                ))}
            </FilterPopover>

            <FilterPopover
                label="Source"
                value={inboxSourceFilterLabel(sourceProductFilter)}
                icon={<IconTarget />}
                active={sourceProductFilter.length > 0}
            >
                {INBOX_SOURCE_OPTIONS.map((option) => (
                    <FilterItem
                        key={option.value}
                        icon={option.icon}
                        label={option.label}
                        active={sourceProductFilter.includes(option.value)}
                        onClick={() => toggleSourceProduct(option.value)}
                    />
                ))}
            </FilterPopover>

            <FilterPopover
                label="Priority"
                value={inboxPriorityFilterLabel(priorityFilter)}
                icon={<IconFlag />}
                active={priorityFilter.length > 0}
            >
                {INBOX_PRIORITY_OPTIONS.map((priority) => (
                    <FilterItem
                        key={priority}
                        icon={
                            <span
                                className="size-2 rounded-full"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ backgroundColor: PRIORITY_ACCENT[priority] }}
                            />
                        }
                        label={
                            <span>
                                {priority}
                                <span className="text-muted"> · {PRIORITY_MEANING[priority].label}</span>
                            </span>
                        }
                        active={priorityFilter.includes(priority)}
                        onClick={() => togglePriority(priority)}
                    />
                ))}
            </FilterPopover>

            {onRefresh && (
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    icon={<IconRefresh />}
                    loading={refreshing}
                    tooltip="Refresh"
                    aria-label="Refresh"
                    onClick={onRefresh}
                    className="bg-surface-primary ml-auto"
                />
            )}
        </div>
    )
}
