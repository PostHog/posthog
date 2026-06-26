import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo, useRef } from 'react'

import { IconChevronDown, IconClock, IconRefresh, IconX } from '@posthog/icons'
import {
    LemonBadge,
    LemonButton,
    LemonCheckbox,
    LemonDropdown,
    LemonInput,
    LemonInputSelect,
    LemonSegmentedButton,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { useBulkSelection } from 'lib/lemon-ui/LemonTable/useBulkSelection'
import { stripMarkdown } from 'lib/utils/markdown'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { tagsModel } from '~/models/tagsModel'
import { ProductKey } from '~/queries/schema/schema-general'

import {
    AssigneeDisplay,
    AssigneeIconDisplay,
    AssigneeLabelDisplay,
    AssigneeResolver,
    AssigneeSelect,
} from '../../components/Assignee'
import { ChannelsTag } from '../../components/Channels/ChannelsTag'
import { ComposeTicketButton } from '../../components/ComposeTicket'
import { ConversationsDisabledBanner } from '../../components/ConversationsDisabledBanner'
import { IdentityBadge } from '../../components/IdentityBadge/IdentityBadge'
import { SavedViewsButton } from '../../components/SavedViews/SavedViewsButton'
import { ScenesTabs } from '../../components/ScenesTabs'
import { SlaDisplay } from '../../components/SlaDisplay'
import {
    type AITriageFilterValue,
    type Ticket,
    type TicketSlaState,
    type TicketStatus,
    type TicketTagsMatch,
    aiTriageFilterOptions,
    aiTriageProcessingLabel,
    aiTriageResultLabel,
    aiTriageResultTagType,
    aiTriageTicketTypeLabel,
    channelOptions,
    priorityMultiselectOptions,
    slaOptions,
    statusMultiselectOptions,
    statusOptionsWithoutAll,
} from '../../types'
import { SUPPORT_TICKETS_PAGE_SIZE, supportTicketsSceneLogic } from './supportTicketsSceneLogic'

export const scene: SceneExport = {
    component: SupportTicketsScene,
    logic: supportTicketsSceneLogic,
    productKey: ProductKey.CONVERSATIONS,
}

export const SUPPORT_TICKETS_TABLE_COLUMNS: LemonTableColumns<Ticket> = [
    {
        title: 'Ticket',
        key: 'ticket_number',
        width: 80,
        sorter: true,
        render: (_, ticket) => <span className="text-xs font-mono text-muted-alt">{ticket.ticket_number}</span>,
    },
    {
        title: 'Person',
        key: 'customer',
        render: (_, ticket) => (
            <div className="flex items-center gap-2">
                <PersonDisplay
                    person={
                        ticket.person
                            ? {
                                  id: ticket.person.id,
                                  distinct_id: ticket.distinct_id,
                                  distinct_ids: ticket.person.distinct_ids,
                                  // Merge anonymous_traits as fallback for missing person properties
                                  properties: {
                                      ...ticket.anonymous_traits,
                                      ...ticket.person.properties,
                                  },
                              }
                            : {
                                  distinct_id: ticket.distinct_id,
                                  properties: ticket.anonymous_traits || {},
                              }
                    }
                    withIcon
                />
                {ticket.identity_verified === false && <IdentityBadge verified={false} iconOnly />}
            </div>
        ),
    },
    {
        title: 'Last message',
        key: 'last_message',
        render: (_, ticket) => (
            <div className="flex items-center gap-2">
                {ticket.last_message_text ? (
                    <span
                        className={clsx('text-xs truncate max-w-md', {
                            'text-muted-alt': ticket.unread_team_count === 0,
                            'font-medium': ticket.unread_team_count > 0,
                        })}
                    >
                        {stripMarkdown(ticket.last_message_text)}
                    </span>
                ) : (
                    <span className="text-muted-alt text-xs">—</span>
                )}
                {ticket.unread_team_count > 0 && (
                    <LemonBadge.Number count={ticket.unread_team_count} size="small" status="primary" />
                )}
            </div>
        ),
    },
    {
        title: 'Status',
        key: 'status',
        render: (_, ticket) => (
            <span className="flex items-center gap-1">
                <LemonTag
                    type={ticket.status === 'resolved' ? 'success' : ticket.status === 'new' ? 'primary' : 'default'}
                >
                    {ticket.status === 'on_hold' ? 'On hold' : ticket.status}
                </LemonTag>
                {ticket.snoozed_until && (
                    <span title={`Snoozed until ${new Date(ticket.snoozed_until).toLocaleString()}`}>
                        <IconClock className="text-muted-alt text-base" />
                    </span>
                )}
            </span>
        ),
    },
    {
        title: 'Priority',
        key: 'priority',
        render: (_, ticket) =>
            ticket.priority ? (
                <LemonTag
                    type={ticket.priority === 'high' ? 'danger' : ticket.priority === 'medium' ? 'warning' : 'default'}
                >
                    {ticket.priority}
                </LemonTag>
            ) : (
                <span className="text-muted-alt text-xs">—</span>
            ),
    },
    {
        title: 'SLA',
        key: 'sla_due_at',
        sorter: true,
        render: (_, ticket) =>
            ticket.sla_due_at ? (
                <SlaDisplay slaDueAt={ticket.sla_due_at} className="text-xs" />
            ) : (
                <span className="text-muted-alt text-xs">—</span>
            ),
    },
    {
        title: 'Assignee',
        key: 'assignee',
        render: (_, ticket) => (
            <AssigneeResolver assignee={ticket.assignee ?? null}>
                {({ assignee }) => <AssigneeDisplay assignee={assignee} size="small" />}
            </AssigneeResolver>
        ),
    },
    {
        title: 'Channel',
        key: 'channel',
        render: (_, ticket) => <ChannelsTag channel={ticket.channel_source} detail={ticket.channel_detail} />,
    },
    {
        title: 'Tags',
        key: 'tags',
        render: (_, ticket) =>
            ticket.tags && ticket.tags.length > 0 ? (
                <ObjectTags tags={ticket.tags} staticOnly />
            ) : (
                <span className="text-muted-alt text-xs">—</span>
            ),
    },
    {
        title: 'Created',
        key: 'created_at',
        sorter: true,
        render: (_, ticket) => {
            return (
                <span className="text-xs text-muted-alt">
                    {ticket.created_at && typeof ticket.created_at === 'string' && <TZLabel time={ticket.created_at} />}
                </span>
            )
        },
    },
    {
        title: 'Updated',
        key: 'updated_at',
        sorter: true,
        align: 'right',
        render: (_, ticket) => {
            return (
                <span className="text-xs text-muted-alt">
                    {ticket.updated_at && typeof ticket.updated_at === 'string' && <TZLabel time={ticket.updated_at} />}
                </span>
            )
        },
    },
]

interface SupportTicketsTableProps {
    embedded?: boolean
}

function SupportTicketsBulkActions(): JSX.Element {
    const { selectedTicketIds, selectedTickets, bulkUpdating } = useValues(supportTicketsSceneLogic)
    const { bulkUpdateStatus } = useActions(supportTicketsSceneLogic)

    const hasSelection = selectedTicketIds.length > 0
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
                if (!value || value === currentStatus) {
                    return
                }
                bulkUpdateStatus(selectedTicketIds, value as TicketStatus)
            }}
            value={currentStatus === 'mixed' ? null : currentStatus}
            placeholder="Mark as"
            loading={bulkUpdating}
            disabledReason={!hasSelection ? 'Select tickets first' : bulkUpdating ? 'Updating…' : undefined}
            options={statusOptionsWithoutAll.map((o) => ({ value: o.value, label: o.label }))}
            size="small"
        />
    )
}

export function SupportTicketsTable({ embedded = false }: SupportTicketsTableProps): JSX.Element {
    const logic = useMountedLogic(supportTicketsSceneLogic)
    const { tickets, ticketsLoading, currentPage, totalCount, sorting, selectedTicketIds } = useValues(logic)
    const { setCurrentPage, setSorting, setSelectedTicketIds } = useActions(logic)
    const { push } = useActions(router)
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
        const aiCol: LemonTableColumns<Ticket>[number] = {
            title: 'AI status',
            key: 'ai_triage',
            render: (_, ticket: Ticket) => {
                const triage = ticket.ai_triage
                if (!triage || !triage.status) {
                    return <span className="text-muted-alt text-xs">—</span>
                }
                if (triage.status === 'in_progress') {
                    return (
                        <span className="flex items-center gap-1 text-xs">
                            <Spinner className="text-sm" />
                            {aiTriageProcessingLabel}
                        </span>
                    )
                }
                if (triage.result) {
                    const tooltipContent = [
                        triage.ticket_type &&
                            `Type: ${aiTriageTicketTypeLabel[triage.ticket_type] ?? triage.ticket_type}`,
                        triage.confidence != null && `Confidence: ${(triage.confidence * 100).toFixed(0)}%`,
                        triage.attempts != null && `Attempts: ${triage.attempts}`,
                    ]
                        .filter(Boolean)
                        .join(' · ')
                    return (
                        <Tooltip title={tooltipContent || undefined}>
                            <LemonTag type={aiTriageResultTagType(triage.result)}>
                                {aiTriageResultLabel[triage.result]}
                            </LemonTag>
                        </Tooltip>
                    )
                }
                return <span className="text-muted-alt text-xs">—</span>
            },
        }
        let base = embedded
            ? SUPPORT_TICKETS_TABLE_COLUMNS.filter((col) => 'key' in col && col.key !== 'customer')
            : SUPPORT_TICKETS_TABLE_COLUMNS
        if (aiEnabled) {
            const createdIdx = base.findIndex((col) => 'key' in col && col.key === 'priority')
            base = [...base.slice(0, createdIdx), aiCol, ...base.slice(createdIdx)]
        }
        return [checkboxCol, ...base]
    }, [embedded, aiEnabled, isSomeOnPageSelected, isAllOnPageSelected, toggleAllOnPage, selectedKeysSet, toggleRow])

    return (
        <LemonTable<Ticket>
            dataSource={tickets}
            rowKey="id"
            loading={ticketsLoading}
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

export function SupportTicketsTableFilters(): JSX.Element {
    const logic = useMountedLogic(supportTicketsSceneLogic)
    const {
        searchQuery,
        statusFilter,
        priorityFilter,
        channelFilter,
        slaFilter,
        aiTriageResultFilter,
        assigneeFilter,
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
                    <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
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
                    <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
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
                        <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
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
                    <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
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
                {(tagsFilter.length > 0 || tagsExcludeFilter.length > 0) && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconX />}
                        onClick={() => {
                            setTagsFilter([])
                            setTagsExcludeFilter([])
                        }}
                        tooltip="Clear tag filter"
                    />
                )}
                <AssigneeSelect
                    assignee={assigneeFilter === 'all' || assigneeFilter === 'unassigned' ? null : assigneeFilter}
                    onChange={(assignee) => setAssigneeFilter(assignee ?? 'all')}
                >
                    {(resolvedAssignee, isOpen) => (
                        <LemonButton size="small" type="secondary" active={isOpen} sideIcon={<IconChevronDown />}>
                            <span className="flex items-center gap-1">
                                <AssigneeIconDisplay assignee={resolvedAssignee} size="small" />
                                <AssigneeLabelDisplay
                                    assignee={resolvedAssignee}
                                    size="small"
                                    placeholder="All assignees"
                                />
                            </span>
                        </LemonButton>
                    )}
                </AssigneeSelect>
                <LemonCheckbox
                    checked={assigneeFilter === 'unassigned'}
                    onChange={(checked) => setAssigneeFilter(checked ? 'unassigned' : 'all')}
                    label="Unassigned only"
                />
            </div>
            <div className="flex items-center gap-2">
                <SupportTicketsBulkActions />
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
