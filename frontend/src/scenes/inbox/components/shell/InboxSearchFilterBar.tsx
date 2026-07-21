import { useActions, useValues } from 'kea'

import { IconRefresh, IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import {
    INBOX_PRIORITY_OPTIONS,
    INBOX_SORT_OPTIONS,
    INBOX_SOURCE_OPTIONS,
    PRIORITY_ACCENT,
    PRIORITY_MEANING,
    inboxSortOptionKey,
} from '../../filterOptions'
import { InboxSortDirection, InboxSortField, inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { SignalReportPriority } from '../../types'

interface InboxSearchFilterBarProps {
    searchPlaceholder?: string
    /** Triggers a reload of the report list (lives on `inboxSceneLogic`). */
    onRefresh?: () => void
    refreshing?: boolean
}

/**
 * Search input + Sort / Source / Priority filters + refresh. There is no status
 * filter (desktop dropped it; status is a fixed request constant). Sort is a
 * single-select; Source and Priority are standard multi-select menus — a value
 * shows as a removable chip, an empty filter reads "All …", and the dropdown
 * offers "Clear all" to reset. Filter state is persisted via `inboxFiltersLogic`;
 * the central scene reloads on change.
 */
export function InboxSearchFilterBar({
    searchPlaceholder = 'Search by title or description…',
    onRefresh,
    refreshing,
}: InboxSearchFilterBarProps): JSX.Element {
    const { searchQuery, sortField, sortDirection, sourceProductFilter, priorityFilter } = useValues(inboxFiltersLogic)
    const { setSearchQuery, setSort, setSourceProductFilter, setPriorityFilter } = useActions(inboxFiltersLogic)

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

            <LemonSelect
                size="small"
                value={inboxSortOptionKey(sortField, sortDirection)}
                onChange={(key) => {
                    const [field, direction] = key.split(':')
                    setSort(field as InboxSortField, direction as InboxSortDirection)
                }}
                options={INBOX_SORT_OPTIONS.map((option) => ({
                    value: inboxSortOptionKey(option.field, option.direction),
                    label: option.label,
                    icon: option.icon,
                }))}
            />

            <LemonInputSelect
                mode="multiple"
                value={sourceProductFilter}
                onChange={setSourceProductFilter}
                options={INBOX_SOURCE_OPTIONS.map((option) => ({
                    key: option.value,
                    label: option.label,
                    labelComponent: (
                        <span className="flex items-center gap-1.5">
                            <span className="flex shrink-0 items-center text-tertiary [&>svg]:size-3.5">
                                {option.icon}
                            </span>
                            {option.label}
                        </span>
                    ),
                }))}
                placeholder="All sources"
                bulkActions="clear-all"
                allowCustomValues={false}
                size="small"
                className="min-w-[150px]"
            />

            <LemonInputSelect
                mode="multiple"
                value={priorityFilter}
                onChange={(priorities) => setPriorityFilter(priorities as SignalReportPriority[])}
                options={INBOX_PRIORITY_OPTIONS.map((priority) => ({
                    key: priority,
                    label: `${priority} · ${PRIORITY_MEANING[priority].label}`,
                    labelComponent: (
                        <span className="flex items-center gap-1.5">
                            <span
                                className="size-2 rounded-full"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ backgroundColor: PRIORITY_ACCENT[priority] }}
                            />
                            <span>
                                {priority}
                                <span className="text-muted"> · {PRIORITY_MEANING[priority].label}</span>
                            </span>
                        </span>
                    ),
                }))}
                placeholder="All priorities"
                bulkActions="clear-all"
                allowCustomValues={false}
                size="small"
                className="min-w-[150px]"
            />

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
