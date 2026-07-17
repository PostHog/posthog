import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconChevronDown, IconFlag, IconRefresh, IconSearch, IconSort, IconTarget } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

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
import { SignalReportPriority } from '../../types'

/**
 * A single filter trigger + dropdown overlay. The trigger stays a quiet, muted chip
 * (matching master's inbox) until its filter is in use, then gains a solid border and
 * shows its value — so the bar only draws attention to filters actually in use. The
 * overlay contents are standard Lemon components. Single-select popovers close on pick;
 * multi-select ones stay open so several values can be toggled in one go.
 */
function FilterPopover({
    label,
    value,
    icon,
    active,
    closeOnClickInside = false,
    children,
}: {
    label: string
    value: string
    icon: JSX.Element
    active: boolean
    closeOnClickInside?: boolean
    children: React.ReactNode
}): JSX.Element {
    const [visible, setVisible] = useState(false)
    return (
        <LemonDropdown
            closeOnClickInside={closeOnClickInside}
            visible={visible}
            onVisibilityChange={setVisible}
            matchWidth={false}
            actionable
            placement="bottom-start"
            overlay={<div className="min-w-[200px] max-w-[260px] deprecated-space-y-px">{children}</div>}
        >
            <button
                type="button"
                aria-label={`${label}: ${value}`}
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

interface InboxSearchFilterBarProps {
    searchPlaceholder?: string
    /** Triggers a reload of the report list (lives on `inboxSceneLogic`). */
    onRefresh?: () => void
    refreshing?: boolean
}

/**
 * Search input + Sort / Source / Priority filter popovers + refresh. There is no
 * status filter (desktop dropped it; status is a fixed request constant). Each
 * popover stays a quiet, muted chip until its filter is in use. Sort is single-select;
 * Source and Priority are multi-select with a "Clear all" to reset to "no filter".
 * Filter state is persisted via `inboxFiltersLogic`; the central scene reloads on change.
 */
export function InboxSearchFilterBar({
    searchPlaceholder = 'Search by title or description…',
    onRefresh,
    refreshing,
}: InboxSearchFilterBarProps): JSX.Element {
    const { searchQuery, sortField, sortDirection, sourceProductFilter, priorityFilter } = useValues(inboxFiltersLogic)
    const { setSearchQuery, setSort, setSourceProductFilter, setPriorityFilter } = useActions(inboxFiltersLogic)

    const activeSort = INBOX_SORT_OPTIONS.find((o) => o.field === sortField && o.direction === sortDirection)
    const activeSortKey = inboxSortOptionKey(sortField, sortDirection)

    const toggleSource = (source: string): void =>
        setSourceProductFilter(
            sourceProductFilter.includes(source)
                ? sourceProductFilter.filter((s) => s !== source)
                : [...sourceProductFilter, source]
        )
    const togglePriority = (priority: SignalReportPriority): void =>
        setPriorityFilter(
            priorityFilter.includes(priority)
                ? priorityFilter.filter((p) => p !== priority)
                : [...priorityFilter, priority]
        )

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
                closeOnClickInside
            >
                {INBOX_SORT_OPTIONS.map((option) => {
                    const isActive = sortField === option.field && sortDirection === option.direction
                    return (
                        <LemonButton
                            key={inboxSortOptionKey(option.field, option.direction)}
                            fullWidth
                            size="small"
                            icon={option.icon}
                            active={isActive}
                            sideIcon={isActive ? <IconCheck /> : null}
                            onClick={() => setSort(option.field, option.direction)}
                        >
                            {option.label}
                        </LemonButton>
                    )
                })}
            </FilterPopover>

            <FilterPopover
                label="Source"
                value={inboxSourceFilterLabel(sourceProductFilter)}
                icon={<IconTarget />}
                active={sourceProductFilter.length > 0}
            >
                {INBOX_SOURCE_OPTIONS.map((option) => {
                    const isActive = sourceProductFilter.includes(option.value)
                    return (
                        <LemonButton
                            key={option.value}
                            fullWidth
                            size="small"
                            icon={option.icon}
                            active={isActive}
                            sideIcon={isActive ? <IconCheck /> : null}
                            onClick={() => toggleSource(option.value)}
                        >
                            {option.label}
                        </LemonButton>
                    )
                })}
                {sourceProductFilter.length > 0 && (
                    <>
                        <LemonDivider className="my-1" />
                        <LemonButton fullWidth size="small" onClick={() => setSourceProductFilter([])}>
                            Clear all
                        </LemonButton>
                    </>
                )}
            </FilterPopover>

            <FilterPopover
                label="Priority"
                value={inboxPriorityFilterLabel(priorityFilter)}
                icon={<IconFlag />}
                active={priorityFilter.length > 0}
            >
                {INBOX_PRIORITY_OPTIONS.map((priority) => {
                    const isActive = priorityFilter.includes(priority)
                    return (
                        <LemonButton
                            key={priority}
                            fullWidth
                            size="small"
                            icon={
                                <span
                                    className="size-2 rounded-full"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ backgroundColor: PRIORITY_ACCENT[priority] }}
                                />
                            }
                            active={isActive}
                            sideIcon={isActive ? <IconCheck /> : null}
                            onClick={() => togglePriority(priority)}
                        >
                            <span>
                                {priority}
                                <span className="text-muted"> · {PRIORITY_MEANING[priority].label}</span>
                            </span>
                        </LemonButton>
                    )
                })}
                {priorityFilter.length > 0 && (
                    <>
                        <LemonDivider className="my-1" />
                        <LemonButton fullWidth size="small" onClick={() => setPriorityFilter([])}>
                            Clear all
                        </LemonButton>
                    </>
                )}
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
