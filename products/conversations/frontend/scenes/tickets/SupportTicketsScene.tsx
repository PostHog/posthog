import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo, useState } from 'react'

import { IconChevronDown, IconRefresh } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDivider,
    LemonDropdown,
    LemonInput,
    LemonInputSelect,
    LemonSegmentedButton,
    LemonTable,
    LemonTableColumns,
} from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { type BulkSelectionContext } from 'lib/lemon-ui/LemonTable/useBulkSelection'
import { newInternalTab } from 'lib/utils/newInternalTab'
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

function SupportTicketsBulkActions({ ctx }: { ctx: BulkSelectionContext<Ticket, string> }): JSX.Element {
    const { bulkUpdating, bulkTagsToAdd } = useValues(supportTicketsSceneLogic)
    const { bulkUpdateStatus, bulkAddTags, setBulkTagsToAdd } = useActions(supportTicketsSceneLogic)
    const { tags: tagsAvailable } = useValues(tagsModel)
    const [dropdownOpen, setDropdownOpen] = useState(false)

    const selectedIds = [...ctx.selectedKeys]
    // Status is derived from the selected rows visible on the current page; a selection spanning
    // pages will show 'mixed' if the on-page rows disagree, which is the safe default.
    const currentStatus = ctx.selectedRecords
        .map((t) => t.status)
        .reduce<TicketStatus | 'mixed' | null>((acc, s) => {
            if (acc === null) {
                return s
            }
            return acc === s ? acc : 'mixed'
        }, null)

    const tagOptions = tagsAvailable?.map((t: string) => ({ key: t, label: t })) || []
    const addTagsLabel =
        bulkTagsToAdd.length > 0
            ? `Add ${bulkTagsToAdd.length} tag${bulkTagsToAdd.length === 1 ? '' : 's'}`
            : 'Add tags'

    return (
        <LemonDropdown
            visible={dropdownOpen}
            onVisibilityChange={setDropdownOpen}
            closeOnClickInside={false}
            overlay={
                <div className="p-2 min-w-64 flex flex-col gap-2">
                    <span className="text-muted text-xs">
                        Update {ctx.selectedCount} selected ticket{ctx.selectedCount === 1 ? '' : 's'}
                    </span>
                    <div className="flex flex-col gap-1">
                        <span className="text-muted text-xs">Mark as</span>
                        <div className="flex flex-col gap-px">
                            {statusOptionsWithoutAll.map((o) => (
                                <LemonButton
                                    key={o.value}
                                    type="tertiary"
                                    size="small"
                                    fullWidth
                                    active={currentStatus === o.value}
                                    loading={bulkUpdating}
                                    onClick={() => {
                                        if (o.value !== currentStatus) {
                                            bulkUpdateStatus(selectedIds, o.value as TicketStatus)
                                        }
                                        ctx.clearSelection()
                                        setDropdownOpen(false)
                                    }}
                                >
                                    {o.label}
                                </LemonButton>
                            ))}
                        </div>
                    </div>
                    <LemonDivider className="my-1" />
                    <div className="flex flex-col gap-2">
                        <span className="text-muted text-xs">Add tags</span>
                        <LemonInputSelect
                            mode="multiple"
                            allowCustomValues
                            value={bulkTagsToAdd}
                            options={tagOptions}
                            onChange={setBulkTagsToAdd}
                            placeholder="Select or type tags..."
                            data-attr="bulk-add-tags-input"
                        />
                        <LemonButton
                            type="primary"
                            size="small"
                            fullWidth
                            center
                            loading={bulkUpdating}
                            disabledReason={bulkTagsToAdd.length === 0 ? 'Select at least one tag' : undefined}
                            onClick={() => {
                                bulkAddTags(selectedIds, bulkTagsToAdd)
                                ctx.clearSelection()
                                setDropdownOpen(false)
                            }}
                        >
                            {addTagsLabel}
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                Update tickets
            </LemonButton>
        </LemonDropdown>
    )
}

export function SupportTicketsTable({
    embedded = false,
    bulkActionsTarget,
}: SupportTicketsTableProps & { bulkActionsTarget?: HTMLElement | null }): JSX.Element {
    const logic = useMountedLogic(supportTicketsSceneLogic)
    const { tickets, ticketsLoading, currentPage, totalCount, sorting } = useValues(logic)
    const { setCurrentPage, setSorting } = useActions(logic)
    const { visibleColumns } = useValues(ticketColumnsLogic)
    const { push } = useActions(router)
    const { currentTeam } = useValues(teamLogic)
    const aiEnabled = !!currentTeam?.conversations_settings?.ai_suggestions_enabled

    const columns = useMemo<LemonTableColumns<Ticket>>(
        () => buildTicketColumns(visibleColumns, { aiEnabled, embedded }),
        [visibleColumns, aiEnabled, embedded]
    )

    return (
        <LemonTable<Ticket, string>
            dataSource={tickets}
            rowKey="id"
            loading={ticketsLoading}
            // Keep rows clickable while a background refresh is in flight; the loading overlay
            // otherwise captures pointer events and blocks navigation on every reload.
            disableTableWhileLoading={false}
            embedded={embedded}
            sorting={sorting}
            onSort={(newSorting) => setSorting(newSorting)}
            noSortingCancellation
            bulkSelection={{
                getKey: (ticket: Ticket): string => ticket.id,
                rowAriaLabel: (ticket: Ticket) => `Select ticket ${ticket.ticket_number}`,
                headerAriaLabel: 'Select all tickets on this page',
                noun: ['ticket', 'tickets'],
                barPortalTarget: bulkActionsTarget,
                renderActions: (ctx) => <SupportTicketsBulkActions ctx={ctx} />,
            }}
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
                const ticketUrl = urls.supportTicketDetail(ticket.ticket_number)
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

export function SupportTicketsTableFilters({
    embedded = false,
    bulkSelectionBarRef,
}: SupportTicketsTableProps & { bulkSelectionBarRef?: (element: HTMLDivElement | null) => void }): JSX.Element {
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
                <div ref={bulkSelectionBarRef} className="flex items-center gap-2 empty:hidden" />
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
    // Render the bulk-action bar into the filters toolbar rather than above the table, so
    // selecting tickets doesn't insert a row that pushes the table down.
    const [bulkBarTarget, setBulkBarTarget] = useState<HTMLDivElement | null>(null)

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
            <SupportTicketsTableFilters bulkSelectionBarRef={setBulkBarTarget} />
            <SupportTicketsTable bulkActionsTarget={bulkBarTarget} />
        </SceneContent>
    )
}
