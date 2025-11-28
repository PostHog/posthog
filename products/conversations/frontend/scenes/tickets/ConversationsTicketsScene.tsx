import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { LemonCard, LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ChannelsTag } from '../../components/Channels/ChannelsTag'
import { ScenesTabs } from '../../components/ScenesTabs'
import type { TicketChannel, TicketSlaState, TicketStatus } from '../../data/tickets'
import { conversationsTicketsSceneLogic } from './conversationsTicketsSceneLogic'

const statusOptions: { value: TicketStatus | 'all'; label: string }[] = [
    { value: 'all', label: 'All statuses' },
    { value: 'open', label: 'Open' },
    { value: 'pending', label: 'Pending' },
    { value: 'resolved', label: 'Resolved' },
]

const channelOptions: { value: TicketChannel | 'all'; label: string }[] = [
    { value: 'all', label: 'All channels' },
    { value: 'widget', label: 'Widget' },
    { value: 'slack', label: 'Slack' },
    { value: 'email', label: 'Email' },
]

const resolutionOptions: { value: 'all' | 'ai' | 'human'; label: string }[] = [
    { value: 'all', label: 'AI + Human' },
    { value: 'ai', label: 'AI only' },
    { value: 'human', label: 'Human only' },
]

const slaOptions: { value: TicketSlaState | 'all'; label: string }[] = [
    { value: 'all', label: 'All SLA states' },
    { value: 'on-track', label: 'On track' },
    { value: 'at-risk', label: 'At risk' },
    { value: 'breached', label: 'Breached' },
]

export const scene: SceneExport = {
    component: ConversationsTicketsScene,
    logic: conversationsTicketsSceneLogic,
}

export function ConversationsTicketsScene(): JSX.Element {
    const logic = conversationsTicketsSceneLogic()
    const { filteredTickets, metrics, statusFilter, channelFilter, resolutionFilter, slaFilter } = useValues(logic)
    const { setStatusFilter, setChannelFilter, setResolutionFilter, setSlaFilter } = useActions(logic)
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
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
                <LemonCard hoverEffect={false}>
                    <div className="text-sm text-muted-alt">Open</div>
                    <div className="text-3xl font-semibold">{metrics.open}</div>
                </LemonCard>
                <LemonCard hoverEffect={false}>
                    <div className="text-sm text-muted-alt">Pending</div>
                    <div className="text-3xl font-semibold">{metrics.pending}</div>
                </LemonCard>
                <LemonCard hoverEffect={false}>
                    <div className="text-sm text-muted-alt">SLA risk</div>
                    <div className="text-3xl font-semibold">{metrics.atRisk}</div>
                </LemonCard>
                <LemonCard hoverEffect={false}>
                    <div className="text-sm text-muted-alt">AI containment</div>
                    <div className="text-3xl font-semibold">{metrics.aiContainment}%</div>
                </LemonCard>
            </div>

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
                    value={resolutionFilter}
                    onChange={(value) => value && setResolutionFilter(value as 'all' | 'ai' | 'human')}
                    options={resolutionOptions}
                    size="small"
                    placeholder="Resolution"
                />
                <LemonSelect
                    value={slaFilter}
                    onChange={(value) => value && setSlaFilter(value as TicketSlaState | 'all')}
                    options={slaOptions}
                    size="small"
                    placeholder="SLA"
                />
            </div>

            <LemonTable
                dataSource={filteredTickets}
                rowKey="id"
                onRow={(ticket) => ({
                    onClick: () => push(urls.conversationsTicketDetail(ticket.id)),
                })}
                columns={[
                    {
                        title: 'Ticket',
                        key: 'ticket',
                        render: (_, ticket) => (
                            <div>
                                <div className="font-medium">{ticket.subject}</div>
                                <div className="text-xs text-muted-alt">{ticket.customer}</div>
                            </div>
                        ),
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, ticket) => (
                            <div className="flex items-center gap-2">
                                <LemonTag type={ticket.status === 'resolved' ? 'success' : 'default'}>
                                    {ticket.status}
                                </LemonTag>
                                <LemonTag type={ticket.aiContained ? 'success' : 'warning'}>
                                    {ticket.aiContained ? 'AI contained' : 'Human needed'}
                                </LemonTag>
                            </div>
                        ),
                    },
                    {
                        title: 'Channel',
                        key: 'channel',
                        render: (_, ticket) => <ChannelsTag channel={ticket.channel} />,
                    },
                    {
                        title: 'Assignee',
                        dataIndex: 'assignedTo',
                    },
                    {
                        title: 'Priority',
                        key: 'priority',
                        render: (_, ticket) => (
                            <LemonTag
                                type={
                                    ticket.priority === 'high'
                                        ? 'danger'
                                        : ticket.priority === 'medium'
                                          ? 'warning'
                                          : 'muted'
                                }
                            >
                                {ticket.priority}
                            </LemonTag>
                        ),
                    },
                    {
                        title: 'SLA',
                        key: 'slaState',
                        render: (_, ticket) => (
                            <LemonTag
                                type={
                                    ticket.slaState === 'on-track'
                                        ? 'success'
                                        : ticket.slaState === 'at-risk'
                                          ? 'warning'
                                          : 'danger'
                                }
                            >
                                {ticket.slaState}
                            </LemonTag>
                        ),
                    },
                    {
                        title: 'Updated',
                        key: 'updatedAgoMinutes',
                        align: 'right',
                        render: (_, ticket) => (
                            <span className="text-xs text-muted-alt">{ticket.updatedAgoMinutes} min ago</span>
                        ),
                    },
                ]}
            />
        </SceneContent>
    )
}
