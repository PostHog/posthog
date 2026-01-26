import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronDown, IconRefresh } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonCheckbox, LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TZLabel } from 'lib/components/TZLabel'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    AssigneeDisplay,
    AssigneeIconDisplay,
    AssigneeLabelDisplay,
    AssigneeResolver,
    AssigneeSelect,
} from '../../components/Assignee'
import { ChannelsTag } from '../../components/Channels/ChannelsTag'
import { ScenesTabs } from '../../components/ScenesTabs'
import { type Ticket, type TicketPriority, type TicketStatus, priorityOptions, statusOptions } from '../../types'
import { supportTicketsSceneLogic } from './supportTicketsSceneLogic'

export const scene: SceneExport = {
    component: SupportTicketsScene,
    logic: supportTicketsSceneLogic,
}

export function SupportTicketsScene(): JSX.Element {
    const logic = supportTicketsSceneLogic()
    const { filteredTickets, statusFilter, priorityFilter, assigneeFilter, dateFrom, dateTo, ticketsLoading } =
        useValues(logic)
    const { setStatusFilter, setPriorityFilter, setAssigneeFilter, setDateRange, loadTickets } = useActions(logic)
    const { push } = useActions(router)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Support"
                description=""
                resourceType={{
                    type: 'conversation',
                }}
            />
            <ScenesTabs />
            <div className="flex flex-wrap gap-3 items-center justify-between">
                <div className="flex flex-wrap gap-3 items-center">
                    <DateFilter
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={(dateFrom, dateTo) => setDateRange(dateFrom, dateTo)}
                    />
                    <LemonSelect
                        value={statusFilter}
                        onChange={(value) => value && setStatusFilter(value as TicketStatus | 'all')}
                        options={statusOptions}
                        size="small"
                        placeholder="Status"
                    />
                    <LemonSelect
                        value={priorityFilter}
                        onChange={(value) => value && setPriorityFilter(value as TicketPriority | 'all')}
                        options={[{ value: 'all', label: 'All priorities' }, ...priorityOptions]}
                        size="small"
                        placeholder="Priority"
                    />
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

            <LemonTable<Ticket>
                dataSource={filteredTickets}
                rowKey="id"
                loading={ticketsLoading}
                onRow={(ticket) => ({
                    onClick: () => push(urls.supportTicketDetail(ticket.id)),
                })}
                rowClassName={(ticket) =>
                    clsx({
                        'bg-primary-alt-highlight': ticket.unread_team_count > 0,
                    })
                }
                columns={[
                    {
                        title: 'Ticket',
                        key: 'key',
                        width: 80,
                        render: (_, ticket) => (
                            <span className="text-xs font-mono text-muted-alt">{ticket.ticket_number}</span>
                        ),
                    },
                    {
                        title: 'Person',
                        key: 'customer',
                        render: (_, ticket) => (
                            <div className="flex items-center gap-2">
                                <PersonDisplay person={{ distinct_id: ticket.distinct_id }} withIcon />
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
                                        {ticket.last_message_text}
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
                            <LemonTag
                                type={
                                    ticket.status === 'resolved'
                                        ? 'success'
                                        : ticket.status === 'new'
                                          ? 'primary'
                                          : 'default'
                                }
                            >
                                {ticket.status === 'on_hold' ? 'On hold' : ticket.status}
                            </LemonTag>
                        ),
                    },
                    {
                        title: 'Priority',
                        key: 'priority',
                        render: (_, ticket) =>
                            ticket.priority ? (
                                <LemonTag
                                    type={
                                        ticket.priority === 'high'
                                            ? 'danger'
                                            : ticket.priority === 'medium'
                                              ? 'warning'
                                              : 'default'
                                    }
                                >
                                    {ticket.priority}
                                </LemonTag>
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
                        render: (_, ticket) => <ChannelsTag channel={ticket.channel_source} />,
                    },
                    {
                        title: 'Created',
                        key: 'created_at',
                        render: (_, ticket) => {
                            return (
                                <span className="text-xs text-muted-alt">
                                    {ticket.created_at && typeof ticket.created_at === 'string' && (
                                        <TZLabel time={ticket.created_at} />
                                    )}
                                </span>
                            )
                        },
                    },
                    {
                        title: 'Updated',
                        key: 'updated_at',
                        align: 'right',
                        render: (_, ticket) => {
                            return (
                                <span className="text-xs text-muted-alt">
                                    {ticket.updated_at && typeof ticket.updated_at === 'string' && (
                                        <TZLabel time={ticket.updated_at} />
                                    )}
                                </span>
                            )
                        },
                    },
                ]}
            />
        </SceneContent>
    )
}
