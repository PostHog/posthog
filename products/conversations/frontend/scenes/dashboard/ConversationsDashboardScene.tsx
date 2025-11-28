import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconClock } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ChannelsTag } from '../../components/Channels/ChannelsTag'
import { ScenesTabs } from '../../components/ScenesTabs'
import { conversationsKpis } from '../../data/kpis'
import { escalationTickets, ticketPods } from '../../data/tickets'
import { type ChannelFilter, conversationsDashboardSceneLogic } from './conversationsDashboardSceneLogic'

export const scene: SceneExport = {
    component: ConversationsDashboardScene,
    logic: conversationsDashboardSceneLogic,
}

const channelOptions = [
    { value: 'all', label: 'All channels' },
    { value: 'widget', label: 'Widget' },
    { value: 'slack', label: 'Slack' },
    { value: 'email', label: 'Email' },
]

export function ConversationsDashboardScene(): JSX.Element {
    const logic = conversationsDashboardSceneLogic()
    const { channelFilter } = useValues(logic)
    const { setChannelFilter } = useActions(logic)
    const [dateRange, setDateRange] = useState<{ dateFrom: string | null; dateTo: string | null }>({
        dateFrom: '-7d',
        dateTo: null,
    })
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
            <div className="flex flex-wrap gap-3 items-center">
                <DateFilter
                    dateFrom={dateRange.dateFrom}
                    dateTo={dateRange.dateTo}
                    onChange={(dateFrom, dateTo) => setDateRange({ dateFrom, dateTo })}
                />
                <LemonSelect
                    value={channelFilter}
                    onChange={(value) => value && setChannelFilter(value as ChannelFilter)}
                    options={channelOptions}
                    placeholder="Channel filter"
                    size="small"
                />
            </div>

            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                {conversationsKpis.map((kpi) => (
                    <LemonCard key={kpi.key} hoverEffect={false}>
                        <div className="text-xs uppercase text-muted-alt tracking-wide">{kpi.label}</div>
                        <div className="mt-1 text-2xl font-semibold">{kpi.value}</div>
                        <div className="mt-2">
                            <LemonTag type={kpi.delta >= 0 ? 'success' : 'danger'} size="small">
                                {`${kpi.delta >= 0 ? '+' : ''}${kpi.delta}% ${kpi.deltaPeriod}`}
                            </LemonTag>
                        </div>
                    </LemonCard>
                ))}
            </div>

            <div className="grid gap-4 lg:grid-cols-3">
                <div className="lg:col-span-3 rounded border border-light bg-bg-light p-4">
                    <div className="mb-3 flex items-center justify-between">
                        <div>
                            <h3 className="text-lg font-semibold">Escalation firehose</h3>
                            <p className="text-sm text-muted-alt">
                                AI fallbacks waiting for human intervention, sorted by urgency.
                            </p>
                        </div>
                        <LemonButton to={urls.conversationsTickets() + '?view=escalated'} size="small" type="secondary">
                            View queue
                        </LemonButton>
                    </div>
                    <LemonTable
                        dataSource={escalationTickets}
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
                                        <div className="font-medium">{ticket.id}</div>
                                        <div className="text-muted-alt text-xs">{ticket.subject}</div>
                                    </div>
                                ),
                            },
                            {
                                title: 'Reason',
                                dataIndex: 'reason',
                                className: 'w-1/3',
                            },
                            {
                                title: 'Channel',
                                key: 'channel',
                                render: (_, ticket) => <ChannelsTag channel={ticket.channel} />,
                            },
                            {
                                title: 'Assignee',
                                key: 'owner',
                                render: (_, ticket) => (
                                    <span className="text-xs text-muted-alt">{ticket.owner || 'Unassigned'}</span>
                                ),
                            },
                            {
                                title: 'Open',
                                key: 'minutesOpen',
                                align: 'right',
                                render: (_, ticket) => (
                                    <span className="text-xs text-muted-alt">{ticket.minutesOpen} min</span>
                                ),
                            },
                        ]}
                    />
                </div>
            </div>

            <div className="grid gap-4 lg:grid-cols-3">
                {ticketPods.map((pod) => (
                    <LemonCard key={pod.key} hoverEffect={false}>
                        <div className="mb-3 flex items-start justify-between gap-2">
                            <div>
                                <h3 className="text-base font-semibold">{pod.title}</h3>
                                <p className="text-sm text-muted-alt">{pod.description}</p>
                            </div>
                            <LemonButton to={pod.targetUrl} size="small" type="secondary">
                                View all
                            </LemonButton>
                        </div>
                        <div className="space-y-3">
                            {pod.tickets.map((ticket) => (
                                <div
                                    key={ticket.id}
                                    className="rounded border border-light px-3 py-2 cursor-pointer"
                                    onClick={() => push(urls.conversationsTicketDetail(ticket.id))}
                                >
                                    <div className="flex items-center justify-between text-sm font-medium">
                                        <span>{ticket.subject}</span>
                                        <span className="text-xs text-muted-alt">{ticket.minutesOpen} min</span>
                                    </div>
                                    <div className="mt-1 flex items-center gap-2 text-xs text-muted-alt">
                                        <IconClock />
                                        <span>{ticket.customer}</span>
                                        <ChannelsTag channel={ticket.channel} />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </LemonCard>
                ))}
            </div>
        </SceneContent>
    )
}
