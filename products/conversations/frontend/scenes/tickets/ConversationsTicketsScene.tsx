import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonBadge, LemonCheckbox, LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { MemberSelect } from 'lib/components/MemberSelect'
import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ChannelsTag } from '../../components/Channels/ChannelsTag'
import { ScenesTabs } from '../../components/ScenesTabs'
import { type Ticket, type TicketPriority, type TicketStatus, priorityOptions, statusOptions } from '../../types'
import { conversationsTicketsSceneLogic } from './conversationsTicketsSceneLogic'

export const scene: SceneExport = {
    component: ConversationsTicketsScene,
    logic: conversationsTicketsSceneLogic,
}

export function ConversationsTicketsScene(): JSX.Element {
    const logic = conversationsTicketsSceneLogic()
    const {
        filteredTickets,
        statusFilter,
        priorityFilter,
        assigneeFilter,
        dateFrom,
        dateTo,
        ticketsLoading,
        autoUpdateEnabled,
    } = useValues(logic)
    const { setStatusFilter, setPriorityFilter, setAssigneeFilter, setDateRange, setAutoUpdate } = useActions(logic)
    const { push } = useActions(router)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Conversations"
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
                    <MemberSelect
                        value={typeof assigneeFilter === 'number' ? assigneeFilter : null}
                        onChange={(user) => setAssigneeFilter(user?.id ?? 'all')}
                    />
                    <LemonCheckbox
                        checked={assigneeFilter === 'unassigned'}
                        onChange={(checked) => setAssigneeFilter(checked ? 'unassigned' : 'all')}
                        label="Unassigned only"
                    />
                </div>
                <LemonCheckbox checked={autoUpdateEnabled} onChange={setAutoUpdate} label="Autoupdate" />
            </div>

            <LemonTable<Ticket>
                dataSource={filteredTickets}
                rowKey="id"
                loading={ticketsLoading}
                onRow={(ticket) => ({
                    onClick: () => push(urls.conversationsTicketDetail(ticket.id)),
                })}
                rowClassName={(ticket) =>
                    clsx({
                        'bg-primary-alt-highlight': ticket.unread_team_count > 0,
                    })
                }
                columns={[
                    {
                        title: 'Ticket',
                        key: 'ticket',
                        render: (_, ticket) => (
                            <div>
                                <div className="flex items-center gap-2">
                                    <span
                                        className={clsx('font-medium', {
                                            'font-bold': ticket.unread_team_count > 0,
                                        })}
                                    >
                                        <PersonDisplay noLink noPopover person={{ distinct_id: ticket.distinct_id }} />
                                    </span>
                                    {ticket.unread_team_count > 0 && (
                                        <LemonBadge.Number
                                            count={ticket.unread_team_count}
                                            size="small"
                                            status="primary"
                                        />
                                    )}
                                    {ticket.message_count > 0 && (
                                        <LemonTag type="muted" size="small">
                                            {ticket.message_count}
                                        </LemonTag>
                                    )}
                                </div>
                                {ticket.last_message_text && (
                                    <div
                                        className={clsx('text-xs truncate max-w-md', {
                                            'text-muted-alt': ticket.unread_team_count === 0,
                                            'font-medium': ticket.unread_team_count > 0,
                                        })}
                                    >
                                        {ticket.last_message_text}
                                    </div>
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
                        render: (_, ticket) =>
                            ticket.assigned_to_user ? (
                                <div className="flex flex-row items-center flex-nowrap">
                                    <ProfilePicture user={ticket.assigned_to_user} size="md" showName />
                                </div>
                            ) : (
                                <span className="text-muted-alt text-xs">Unassigned</span>
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
