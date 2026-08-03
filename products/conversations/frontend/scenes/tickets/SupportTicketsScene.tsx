import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useEffect, useMemo, useRef } from 'react'

import { IconChevronDown, IconRefresh } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDropdown,
    LemonInput,
    LemonInputSelect,
    LemonSegmentedButton,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    Tooltip,
} from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { useBulkSelection } from 'lib/lemon-ui/LemonTable/useBulkSelection'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { pluralize } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { tagsModel } from '~/models/tagsModel'
import { ProductKey } from '~/queries/schema/schema-general'

import { AssigneeMultiSelect } from '../../components/Assignee'
import { clearFilterButtonProps } from '../../components/clearFilterButtonProps'
import { ComposeTicketButton } from '../../components/ComposeTicket'
import { ConversationsDisabledBanner } from '../../components/ConversationsDisabledBanner'
import { SavedViewsButton } from '../../components/SavedViews/SavedViewsButton'
import { ScenesTabs } from '../../components/ScenesTabs'
import {
    type AITriageFilterValue,
    type Ticket,
    type TicketSlaState,
    type TicketStatus,
    type TicketTagsMatch,
    aiTriageFilterOptions,
    channelOptions,
    priorityMultiselectOptions,
    slaOptions,
    statusMultiselectOptions,
    statusOptionsWithoutAll,
} from '../../types'
import { SUPPORT_TICKETS_PAGE_SIZE, supportTicketsSceneLogic } from './supportTicketsSceneLogic'
import { buildTicketColumns } from './ticketColumns'
import { TicketColumnsDropdown } from './TicketColumnsDropdown'
import { ticketColumnsLogic } from './ticketColumnsLogic'

export const scene: SceneExport = {
    component: SupportTicketsScene,
    logic: supportTicketsSceneLogic,
    productKey: ProductKey.CONVERSATIONS,
}

interface SupportTicketsTableProps {
    embedded?: boolean
}

function SupportTicketsBulkActions(): JSX.Element {
    const { selectedTicketIds, selectedTickets, editableSelectedTicketIds, bulkUpdating } =
        useValues(supportTicketsSceneLogic)
    const { bulkUpdateStatus } = useActions(supportTicketsSceneLogic)

    const hasSelection = selectedTicketIds.length > 0
    const editableTicketIds = editableSelectedTicketIds
    const hasRestrictedSelection = editableTicketIds.length < selectedTicketIds.length
    const selectedStatuses = selectedTickets.map((t) => t.status)
    const currentStatus = selectedStatuses.reduce<TicketStatus | 'mixed' | null>((acc, s) => {
        if (acc === null) {
            return s
        }
        return acc === s ? acc : 'mixed'
    }, null)

    return (
        <LemonSelect
            onChange={(value) => {
                if (!value || value === currentStatus || editableTicketIds.length === 0) {
                    return
                }
                bulkUpdateStatus(editableTicketIds, value as TicketStatus)
            }}
            value={null}
            placeholder="Mark as"
            loading={bulkUpdating}
            disabledReason={
                !hasSelection
                    ? 'Select tickets first'
                    : bulkUpdating
                      ? 'Updating…'
                      : editableTicketIds.length === 0
                        ? "You don't have edit access to any of the selected tickets"
                        : undefined
            }
            tooltip={
                hasRestrictedSelection && editableTicketIds.length > 0
                    ? `${selectedTicketIds.length - editableTicketIds.length} selected ticket(s) will be skipped because you don't have edit access to them`
                    : undefined
            }
            options={statusOptionsWithoutAll.map((o) => ({ value: o.value, label: o.label }))}
            size="small"
        />
    )
}

export function SupportTicketsTable({ embedded = false }: SupportTicketsTableProps): JSX.Element {
    const logic = useMountedLogic(supportTicketsSceneLogic)
    const {
        tickets,
        ticketsLoading,
        currentPage,
        totalCount,
        sorting,
        selectedTicketIds,
        searchQuery,
        hasActiveFilters,
    } = useValues(logic)
    const { setCurrentPage, setSorting, setSelectedTicketIds, clearFiltersKeepingSearch } = useActions(logic)
    const { visibleColumns } = useValues(ticketColumnsLogic)
    const { push } = useActions(router)
    const { searchParams } = useValues(router)
    const { currentTeam } = useValues(teamLogic)
    const aiEnabled = !!currentTeam?.conversations_settings?.ai_suggestions_enabled

    const getKey = useMemo(() => (t: Ticket) => t.id, [])
    const bulk = useBulkSelection<Ticket, string>({ pageRecords: tickets, getKey })
    // `bulk` is a fresh object every render, but its members are individually stable
    // (callbacks/useState/useMemo or primitives). Destructure so hook deps reference the
    // stable members instead of the unstable wrapper object.
    const {
        selectedKeys,
        clearSelection,
        isSomeOnPageSelected,
        isAllOnPageSelected,
        toggleAllOnPage,
        selectedKeysSet,
        toggleRow,
    } = bulk

    useEffect(() => {
        setSelectedTicketIds(selectedKeys)
    }, [selectedKeys, setSelectedTicketIds])

    // Clear hook selection only when kea's selection is reset *externally* (e.g. after a bulk
    // update or page reload). We detect that as a non-empty -> empty transition. Reacting to
    // `selectedTicketIds.length === 0` alone would also fire during the brief window right after
    // the first selection, before the effect above has pushed `selectedKeys` into kea — which
    // would immediately wipe the selection the user just made.
    const prevSelectedTicketIdCount = useRef(selectedTicketIds.length)
    useEffect(() => {
        const wasSelected = prevSelectedTicketIdCount.current > 0
        prevSelectedTicketIdCount.current = selectedTicketIds.length
        if (wasSelected && selectedTicketIds.length === 0 && selectedKeys.length > 0) {
            clearSelection()
        }
    }, [selectedTicketIds, selectedKeys, clearSelection])

    const columns = useMemo<LemonTableColumns<Ticket>>(() => {
        const checkboxCol: LemonTableColumns<Ticket>[number] = {
            key: '__select__' as any,
            width: 32,
            title: (
                <LemonCheckbox
                    checked={isSomeOnPageSelected ? 'indeterminate' : isAllOnPageSelected}
                    onChange={toggleAllOnPage}
                    stopPropagation
                />
            ),
            render: (_, ticket: Ticket, recordIndex: number) => (
                <LemonCheckbox
                    checked={selectedKeysSet.has(ticket.id)}
                    onChange={(_value, event) =>
                        toggleRow(ticket.id, recordIndex, (event.nativeEvent as MouseEvent).shiftKey ?? false)
                    }
                    stopPropagation
                />
            ),
        }
        return [checkboxCol, ...buildTicketColumns(visibleColumns, { aiEnabled, embedded })]
    }, [
        visibleColumns,
        embedded,
        aiEnabled,
        isSomeOnPageSelected,
        isAllOnPageSelected,
        toggleAllOnPage,
        selectedKeysSet,
        toggleRow,
    ])

    const emptyState =
        searchQuery && hasActiveFilters ? (
            <div className="flex flex-col items-center gap-2 py-2">
                <span>No tickets match your search with the current filters applied.</span>
                <LemonButton type="secondary" size="small" onClick={() => clearFiltersKeepingSearch()}>
                    Search again without filters
                </LemonButton>
            </div>
        ) : (
            'No tickets'
        )

    return (
        <LemonTable<Ticket>
            dataSource={tickets}
            rowKey="id"
            emptyState={emptyState}
            loading={ticketsLoading}
            // Keep rows clickable while a background refresh is in flight; the loading overlay
            // otherwise captures pointer events and blocks navigation on every reload.
            disableTableWhileLoading={false}
            embedded={embedded}
            sorting={sorting}
            onSort={(newSorting) => setSorting(newSorting)}
            noSortingCancellation
            pagination={{
                controlled: true,
                currentPage,
                pageSize: SUPPORT_TICKETS_PAGE_SIZE,
                entryCount: totalCount,
                onBackward: currentPage > 1 ? () => setCurrentPage(currentPage - 1) : undefined,
                onForward:
                    currentPage * SUPPORT_TICKETS_PAGE_SIZE < totalCount
                        ? () => setCurrentPage(currentPage + 1)
                        : undefined,
            }}
            onRow={(ticket) => {
                // Carry the active filters / saved view (the list's query string) onto the
                // ticket URL so the ticket's back arrow can return to this exact view. Skip it
                // when embedded (e.g. the person side panel), where the host page's query
                // string isn't the ticket filters.
                const ticketUrl = combineUrl(
                    urls.supportTicketDetail(ticket.ticket_number),
                    embedded ? {} : searchParams
                ).url
                return {
                    onClick: (e: React.MouseEvent) => {
                        if (e.metaKey || e.ctrlKey) {
                            e.preventDefault()
                            e.stopPropagation()
                            newInternalTab(ticketUrl)
                        } else {
                            push(ticketUrl)
                        }
                    },
                    onAuxClick: (e: React.MouseEvent) => {
                        if (e.button === 1) {
                            e.preventDefault()
                            e.stopPropagation()
                            newInternalTab(ticketUrl)
                        }
                    },
                }
            }}
            rowClassName={(ticket) =>
                clsx({
                    'bg-primary-alt-highlight': ticket.unread_team_count > 0,
                })
            }
            columns={columns}
        />
    )
}

export function SupportTicketsTableFilters({ embedded = false }: SupportTicketsTableProps): JSX.Element {
    const logic = useMountedLogic(supportTicketsSceneLogic)
    const {
        searchQuery,
        statusFilter,
        priorityFilter,
        channelFilter,
        slaFilter,
        aiTriageResultFilter,
        assigneeFilterEntries,
        tagsFilter,
        tagsMatch,
        tagsExcludeFilter,
        dateFrom,
        dateTo,
        ticketsLoading,
        totalCount,
        hasActiveFilters,
    } = useValues(logic)
    const {
        setSearchQuery,
        setStatusFilter,
        setPriorityFilter,
        setChannelFilter,
        setSlaFilter,
        setAiTriageResultFilter,
        setAssigneeFilter,
        setTagsFilter,
        setTagsMatch,
        setTagsExcludeFilter,
        setDateRange,
        loadTickets,
    } = useActions(logic)
    const { aiEnabled } = useValues(logic)
    const { tags: tagsAvailable } = useValues(tagsModel)
    const tagOptions = tagsAvailable?.map((t: string) => ({ key: t, label: t })) || []

    return (
        <div className="flex flex-wrap gap-3 items-center justify-between">
            <div className="flex flex-wrap gap-3 items-center">
                <LemonInput
                    type="search"
                    placeholder="Search by ticket #, name, email, or message..."
                    value={searchQuery}
                    onChange={setSearchQuery}
                    size="small"
                    className="min-w-64"
                />
                <Tooltip
                    title={
                        hasActiveFilters || searchQuery
                            ? 'Tickets matching the current filters, search, and view — not the total across all tickets'
                            : 'Tickets in the current view'
                    }
                >
                    {/* Count of tickets matching the current query, shown next to the search/filter
                        controls so it reads as the filtered count rather than an all-time total.
                        Hidden until the first load resolves; dims on subsequent background refreshes. */}
                    <span
                        className={clsx('text-secondary text-sm whitespace-nowrap', ticketsLoading && 'opacity-50')}
                        aria-live="polite"
                    >
                        {ticketsLoading && totalCount === 0 ? null : pluralize(totalCount, 'ticket')}
                    </span>
                </Tooltip>
                <DateFilter
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onChange={(dateFrom, dateTo) => setDateRange(dateFrom, dateTo)}
                />
                <LemonDropdown
                    closeOnClickInside={false}
                    overlay={
                        <div className="space-y-px p-1">
                            {statusMultiselectOptions.map((option) => (
                                <LemonButton
                                    key={option.key}
                                    type="tertiary"
                                    size="small"
                                    fullWidth
                                    icon={
                                        <LemonCheckbox
                                            checked={statusFilter.includes(option.key)}
                                            className="pointer-events-none"
                                        />
                                    }
                                    onClick={() => {
                                        const newFilter = statusFilter.includes(option.key)
                                            ? statusFilter.filter((s) => s !== option.key)
                                            : [...statusFilter, option.key]
                                        setStatusFilter(newFilter)
                                    }}
                                >
                                    {option.label}
                                </LemonButton>
                            ))}
                        </div>
                    }
                >
                    <LemonButton
                        type="secondary"
                        size="small"
                        {...clearFilterButtonProps(
                            statusFilter.length > 0 ? () => setStatusFilter([]) : null,
                            'Clear status filter'
                        )}
                    >
                        {statusFilter.length === 0
                            ? 'All statuses'
                            : statusFilter.length === 1
                              ? statusMultiselectOptions.find((o) => o.key === statusFilter[0])?.label
                              : `${statusFilter.length} statuses`}
                    </LemonButton>
                </LemonDropdown>
                <LemonDropdown
                    closeOnClickInside={false}
                    overlay={
                        <div className="space-y-px p-1">
                            {priorityMultiselectOptions.map((option) => (
                                <LemonButton
                                    key={option.key}
                                    type="tertiary"
                                    size="small"
                                    fullWidth
                                    icon={
                                        <LemonCheckbox
                                            checked={priorityFilter.includes(option.key)}
                                            className="pointer-events-none"
                                        />
                                    }
                                    onClick={() => {
                                        const newFilter = priorityFilter.includes(option.key)
                                            ? priorityFilter.filter((p) => p !== option.key)
                                            : [...priorityFilter, option.key]
                                        setPriorityFilter(newFilter)
                                    }}
                                >
                                    {option.label}
                                </LemonButton>
                            ))}
                        </div>
                    }
                >
                    <LemonButton
                        type="secondary"
                        size="small"
                        {...clearFilterButtonProps(
                            priorityFilter.length > 0 ? () => setPriorityFilter([]) : null,
                            'Clear priority filter'
                        )}
                    >
                        {priorityFilter.length === 0
                            ? 'All priorities'
                            : priorityFilter.length === 1
                              ? priorityMultiselectOptions.find((o) => o.key === priorityFilter[0])?.label
                              : `${priorityFilter.length} priorities`}
                    </LemonButton>
                </LemonDropdown>
                <LemonDropdown
                    closeOnClickInside
                    overlay={
                        <div className="space-y-px p-1">
                            {channelOptions.map((option) => (
                                <LemonButton
                                    key={option.value}
                                    type="tertiary"
                                    size="small"
                                    fullWidth
                                    onClick={() => setChannelFilter(option.value)}
                                    active={channelFilter === option.value}
                                >
                                    {option.label}
                                </LemonButton>
                            ))}
                        </div>
                    }
                >
                    <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                        {channelOptions.find((o) => o.value === channelFilter)?.label ?? 'All channels'}
                    </LemonButton>
                </LemonDropdown>
                <LemonDropdown
                    closeOnClickInside
                    overlay={
                        <div className="space-y-px p-1">
                            {slaOptions.map((option) => (
                                <LemonButton
                                    key={option.value}
                                    type="tertiary"
                                    size="small"
                                    fullWidth
                                    onClick={() => setSlaFilter(option.value as TicketSlaState | 'all')}
                                    active={slaFilter === option.value}
                                >
                                    {option.label}
                                </LemonButton>
                            ))}
                        </div>
                    }
                >
                    <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                        {slaOptions.find((o) => o.value === slaFilter)?.label ?? 'All SLA states'}
                    </LemonButton>
                </LemonDropdown>
                {aiEnabled && (
                    <LemonDropdown
                        closeOnClickInside={false}
                        overlay={
                            <div className="space-y-px p-1">
                                {aiTriageFilterOptions.map((option) => (
                                    <LemonButton
                                        key={option.key}
                                        type="tertiary"
                                        size="small"
                                        fullWidth
                                        icon={
                                            <LemonCheckbox
                                                checked={aiTriageResultFilter.includes(option.key)}
                                                className="pointer-events-none"
                                            />
                                        }
                                        onClick={() => {
                                            const newFilter = aiTriageResultFilter.includes(option.key)
                                                ? aiTriageResultFilter.filter(
                                                      (r: AITriageFilterValue) => r !== option.key
                                                  )
                                                : [...aiTriageResultFilter, option.key]
                                            setAiTriageResultFilter(newFilter)
                                        }}
                                    >
                                        {option.label}
                                    </LemonButton>
                                ))}
                            </div>
                        }
                    >
                        <LemonButton
                            type="secondary"
                            size="small"
                            {...clearFilterButtonProps(
                                aiTriageResultFilter.length > 0 ? () => setAiTriageResultFilter([]) : null,
                                'Clear AI result filter'
                            )}
                        >
                            {aiTriageResultFilter.length === 0
                                ? 'All AI results'
                                : aiTriageResultFilter.length === 1
                                  ? aiTriageFilterOptions.find((o) => o.key === aiTriageResultFilter[0])?.label
                                  : `${aiTriageResultFilter.length} AI results`}
                        </LemonButton>
                    </LemonDropdown>
                )}
                <LemonDropdown
                    closeOnClickInside={false}
                    overlay={
                        <div className="p-2 min-w-64 flex flex-col gap-2">
                            <div className="flex flex-col gap-1">
                                <div className="flex items-center justify-between gap-2">
                                    <span className="text-muted text-xs">Include tags</span>
                                    <LemonSegmentedButton
                                        size="small"
                                        value={tagsMatch}
                                        onChange={(value) => setTagsMatch(value as TicketTagsMatch)}
                                        options={[
                                            { value: 'any', label: 'Match any' },
                                            { value: 'all', label: 'Match all' },
                                        ]}
                                    />
                                </div>
                                <LemonInputSelect
                                    mode="multiple"
                                    allowCustomValues
                                    value={tagsFilter}
                                    options={tagOptions}
                                    onChange={setTagsFilter}
                                    placeholder="Select or type tags..."
                                    data-attr="tags-filter-input"
                                />
                            </div>
                            <div className="flex flex-col gap-1">
                                <span className="text-muted text-xs">Exclude tags</span>
                                <LemonInputSelect
                                    mode="multiple"
                                    allowCustomValues
                                    value={tagsExcludeFilter}
                                    options={tagOptions}
                                    onChange={setTagsExcludeFilter}
                                    placeholder="Exclude tags..."
                                    data-attr="tags-exclude-filter-input"
                                />
                            </div>
                        </div>
                    }
                >
                    <LemonButton
                        type="secondary"
                        size="small"
                        {...clearFilterButtonProps(
                            tagsFilter.length > 0 || tagsExcludeFilter.length > 0
                                ? () => {
                                      setTagsFilter([])
                                      setTagsExcludeFilter([])
                                  }
                                : null,
                            'Clear tag filter'
                        )}
                    >
                        {tagsFilter.length === 0 && tagsExcludeFilter.length === 0
                            ? 'All tags'
                            : [
                                  tagsFilter.length > 0 &&
                                      (tagsFilter.length === 1
                                          ? tagsFilter[0]
                                          : `${tagsMatch === 'all' ? 'all' : 'any'} of ${tagsFilter.length} tags`),
                                  tagsExcludeFilter.length > 0 && `excl. ${tagsExcludeFilter.length}`,
                              ]
                                  .filter(Boolean)
                                  .join(', ')}
                    </LemonButton>
                </LemonDropdown>
                <AssigneeMultiSelect value={assigneeFilterEntries} onChange={setAssigneeFilter} />
            </div>
            <div className="flex items-center gap-2">
                <SupportTicketsBulkActions />
                <TicketColumnsDropdown aiEnabled={aiEnabled} embedded={embedded} />
                <SavedViewsButton id="SupportTicketsScene" />
                <LemonButton
                    type="secondary"
                    icon={<IconRefresh />}
                    loading={ticketsLoading}
                    disabledReason={ticketsLoading ? 'Loading tickets...' : undefined}
                    onClick={loadTickets}
                    size="small"
                    data-attr="refresh-tickets"
                >
                    Refresh
                </LemonButton>
            </div>
        </div>
    )
}

export function SupportTicketsScene(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const conversationsDisabled = !!currentTeam && !currentTeam.conversations_enabled

    return (
        <SceneContent className="pb-4">
            <SceneTitleSection
                name="Support"
                description=""
                resourceType={{
                    type: 'conversation',
                }}
                actions={<ComposeTicketButton />}
            />
            <ScenesTabs />
            {conversationsDisabled ? <ConversationsDisabledBanner /> : null}
            <SupportTicketsTableFilters />
            <SupportTicketsTable />
        </SceneContent>
    )
}
