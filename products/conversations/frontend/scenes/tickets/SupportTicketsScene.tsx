import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronDown, IconClock, IconRefresh, IconX } from '@posthog/icons'
import {
    LemonBadge,
    LemonButton,
    LemonCheckbox,
    LemonDropdown,
    LemonInput,
    LemonInputSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
} from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { stripMarkdown } from 'lib/utils/stripMarkdown'
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
import { ConversationsDisabledBanner } from '../../components/ConversationsDisabledBanner'
import { SavedViewsButton } from '../../components/SavedViews/SavedViewsButton'
import { ScenesTabs } from '../../components/ScenesTabs'
import { SlaDisplay } from '../../components/SlaDisplay'
import {
    type Ticket,
    type TicketSlaState,
    channelOptions,
    priorityMultiselectOptions,
    slaOptions,
    statusMultiselectOptions,
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

export function SupportTicketsTable({ embedded = false }: SupportTicketsTableProps): JSX.Element {
    const logic = useMountedLogic(supportTicketsSceneLogic)
    const { tickets, ticketsLoading, currentPage, totalCount, sorting } = useValues(logic)
    const { setCurrentPage, setSorting } = useActions(logic)
    const { push } = useActions(router)

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
            columns={
                embedded
                    ? SUPPORT_TICKETS_TABLE_COLUMNS.filter((col) => 'key' in col && col.key !== 'customer')
                    : SUPPORT_TICKETS_TABLE_COLUMNS
            }
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
        assigneeFilter,
        tagsFilter,
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
        setAssigneeFilter,
        setTagsFilter,
        setDateRange,
        loadTickets,
    } = useActions(logic)
    const { tags: tagsAvailable } = useValues(tagsModel)

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
                <LemonDropdown
                    closeOnClickInside={false}
                    overlay={
                        <div className="p-2 min-w-64">
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                value={tagsFilter}
                                options={tagsAvailable?.map((t: string) => ({ key: t, label: t })) || []}
                                onChange={setTagsFilter}
                                placeholder="Select or type tags..."
                                data-attr="tags-filter-input"
                            />
                        </div>
                    }
                >
                    <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                        {tagsFilter.length === 0
                            ? 'All tags'
                            : tagsFilter.length === 1
                              ? tagsFilter[0]
                              : `${tagsFilter.length} tags`}
                    </LemonButton>
                </LemonDropdown>
                {tagsFilter.length > 0 && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconX />}
                        onClick={() => setTagsFilter([])}
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
            />
            <ScenesTabs />
            {conversationsDisabled ? <ConversationsDisabledBanner /> : null}
            <SupportTicketsTableFilters />
            <SupportTicketsTable />
        </SceneContent>
    )
}
