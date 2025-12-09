import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { LemonBadge, LemonCheckbox, LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TZLabel } from 'lib/components/TZLabel'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ChannelsTag } from '../../components/Channels/ChannelsTag'
import { ScenesTabs } from '../../components/ScenesTabs'
import {
    type Ticket,
    type TicketChannel,
    type TicketSlaState,
    type TicketStatus,
    channelOptions,
    slaOptions,
    statusOptions,
} from '../../types'
import { conversationsTicketsSceneLogic } from './conversationsTicketsSceneLogic'

export const scene: SceneExport = {
    component: ConversationsTicketsScene,
    logic: conversationsTicketsSceneLogic,
}

export function ConversationsTicketsScene(): JSX.Element {
    const logic = conversationsTicketsSceneLogic()
    const { filteredTickets, statusFilter, channelFilter, slaFilter, ticketsLoading, autoUpdateEnabled } =
        useValues(logic)
    const { setStatusFilter, setChannelFilter, setSlaFilter, setAutoUpdate } = useActions(logic)
    const { push } = useActions(router)
    const [dateRange, setDateRange] = useState<{ dateFrom: string | null; dateTo: string | null }>({
        dateFrom: '-7d',
        dateTo: null,
    })

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
                        dateFrom={dateRange.dateFrom}
                        dateTo={dateRange.dateTo}
                        onChange={(dateFrom, dateTo) => setDateRange({ dateFrom, dateTo })}
                    />
                    <LemonSelect
                        value={statusFilter}
                        onChange={(value) => value && setStatusFilter(value as TicketStatus | 'all')}
                        options={statusOptions}
                        size="small"
                        placeholder="Status"
                    />
                    <LemonSelect
                        value={channelFilter}
                        onChange={(value) => value && setChannelFilter(value as TicketChannel | 'all')}
                        options={channelOptions}
                        size="small"
                        placeholder="Channel"
                    />
                    <LemonSelect
                        value={slaFilter}
                        onChange={(value) => value && setSlaFilter(value as TicketSlaState | 'all')}
                        options={slaOptions}
                        size="small"
                        placeholder="SLA"
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
