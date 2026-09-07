import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconCompass, IconFlag, IconRefresh, IconSearch, IconSort } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

import { STATUS_LABELS } from 'products/signals/frontend/inbox/components/badges/SignalReportStatusBadge'
import { FilterItem, FilterPopover } from 'products/signals/frontend/inbox/components/shell/filterControls'
import {
    INBOX_PRIORITY_OPTIONS,
    INBOX_SORT_OPTIONS,
    PRIORITY_ACCENT,
    PRIORITY_MEANING,
    inboxPriorityFilterLabel,
    inboxSortOptionKey,
} from 'products/signals/frontend/inbox/filterOptions'
import { SignalReportStatus } from 'products/signals/frontend/inbox/types'
import { prettifyScoutSkillName } from 'products/signals/frontend/inbox/utils/scoutRunsWindow'

import { feedLogic } from './feedLogic'

const STATUS_FILTER_OPTIONS: SignalReportStatus[] = [
    SignalReportStatus.READY,
    SignalReportStatus.PENDING_INPUT,
    SignalReportStatus.IN_PROGRESS,
    SignalReportStatus.CANDIDATE,
    SignalReportStatus.POTENTIAL,
    SignalReportStatus.RESOLVED,
    SignalReportStatus.FAILED,
]

function statusLabel(status: SignalReportStatus): string {
    return STATUS_LABELS[status] ?? status
}

// The customer analytics feed is scout-only, so it drops the inbox's Source filter and promotes the
// per-scout sub-filter to a top-level chip. Everything else mirrors the inbox filter bar.
export function FeedFilterBar(): JSX.Element {
    const {
        searchQuery,
        sortField,
        sortDirection,
        statusFilter,
        priorityFilter,
        scoutFilter,
        scoutNames,
        myReportsOnly,
        reportsResponseLoading,
    } = useValues(feedLogic)
    const {
        setSearchQuery,
        setSort,
        setStatusFilter,
        togglePriority,
        toggleScout,
        clearScoutFilter,
        setMyReportsOnly,
        loadReports,
    } = useActions(feedLogic)

    const activeSort = INBOX_SORT_OPTIONS.find((o) => o.field === sortField && o.direction === sortDirection)
    const activeSortKey = inboxSortOptionKey(sortField, sortDirection)

    return (
        <div className="flex items-center gap-2 flex-wrap w-full">
            <LemonInput
                className="min-w-[220px] max-w-[420px] [&_.LemonInput__input]:pr-4"
                type="search"
                value={searchQuery}
                onChange={setSearchQuery}
                placeholder="Search by title or description…"
                prefix={<IconSearch />}
                size="small"
                data-attr="customer-analytics-reports-search"
            />

            <div className="flex flex-wrap items-center justify-end gap-2 ml-auto max-w-full">
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
                    label="Status"
                    value={statusFilter ? statusLabel(statusFilter) : 'Any status'}
                    icon={<IconCheckCircle />}
                    active={statusFilter !== null}
                >
                    <FilterItem
                        label="Any status"
                        active={statusFilter === null}
                        onClick={() => setStatusFilter(null)}
                    />
                    {STATUS_FILTER_OPTIONS.map((status) => (
                        <FilterItem
                            key={status}
                            label={statusLabel(status)}
                            active={statusFilter === status}
                            onClick={() => setStatusFilter(statusFilter === status ? null : status)}
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

                {scoutNames.length > 0 && (
                    <FilterPopover
                        label="Scout"
                        value={
                            scoutFilter.length === 1
                                ? prettifyScoutSkillName(scoutFilter[0])
                                : `${scoutFilter.length} scouts`
                        }
                        icon={<IconCompass />}
                        active={scoutFilter.length > 0}
                    >
                        {scoutNames.map((skillName) => (
                            <FilterItem
                                key={skillName}
                                label={prettifyScoutSkillName(skillName)}
                                active={scoutFilter.includes(skillName)}
                                onClick={() => toggleScout(skillName)}
                            />
                        ))}
                        {scoutFilter.length > 0 && (
                            <LemonButton size="xsmall" type="tertiary" fullWidth onClick={clearScoutFilter}>
                                Clear
                            </LemonButton>
                        )}
                    </FilterPopover>
                )}

                <LemonCheckbox
                    checked={myReportsOnly}
                    onChange={setMyReportsOnly}
                    label="My reports"
                    info="Reports where you are a suggested reviewer"
                    data-attr="customer-analytics-reports-mine-filter"
                />

                <LemonButton
                    type="secondary"
                    size="xsmall"
                    icon={<IconRefresh />}
                    loading={reportsResponseLoading}
                    tooltip="Refresh"
                    aria-label="Refresh"
                    onClick={() => loadReports(null)}
                    className="bg-surface-primary"
                />
            </div>
        </div>
    )
}
