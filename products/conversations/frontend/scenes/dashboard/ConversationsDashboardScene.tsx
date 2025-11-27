import { useActions, useValues } from 'kea'

import { IconBrowser, IconClock, IconComment } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDivider, LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { IconSlack } from 'lib/lemon-ui/icons'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ScenesTabs } from '../../components/ScenesTabs'
import { configChanges } from '../../data/configChanges'
import { escalationTickets } from '../../data/escalations'
import { conversationsKpis } from '../../data/kpis'
import { ticketPods } from '../../data/ticketPods'
import {
    type ChannelFilter,
    type TimeRange,
    conversationsDashboardSceneLogic,
} from './conversationsDashboardSceneLogic'

const channelIcon: Record<string, JSX.Element> = {
    widget: <IconBrowser />,
    slack: <IconSlack />,
    email: <IconComment />,
}

export const scene: SceneExport = {
    component: ConversationsDashboardScene,
    logic: conversationsDashboardSceneLogic,
}

const timeRangeOptions = [
    { value: '24h', label: 'Last 24h' },
    { value: '7d', label: 'Last 7d' },
    { value: '30d', label: 'Last 30d' },
]

const channelOptions = [
    { value: 'all', label: 'All channels' },
    { value: 'widget', label: 'Widget' },
    { value: 'slack', label: 'Slack' },
    { value: 'email', label: 'Email' },
]

export function ConversationsDashboardScene(): JSX.Element {
    const logic = conversationsDashboardSceneLogic()
    const { timeRange, channelFilter } = useValues(logic)
    const { setTimeRange, setChannelFilter } = useActions(logic)

    return (
        <SceneContent className="space-y-5">
            <ScenesTabs />
            <section className="space-y-1">
                <h1 className="text-2xl font-semibold">Conversations overview</h1>
                <p className="text-muted-alt">
                    KPI snapshots, escalations, and recent content/guidance changes to keep the AI assist tuned.
                </p>
            </section>

            <div className="flex flex-wrap gap-3">
                <LemonSelect
                    value={timeRange}
                    onChange={(value) => value && setTimeRange(value as TimeRange)}
                    options={timeRangeOptions}
                    placeholder="Time range"
                />
                <LemonSelect
                    value={channelFilter}
                    onChange={(value) => value && setChannelFilter(value as ChannelFilter)}
                    options={channelOptions}
                    placeholder="Channel filter"
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

            <div className="grid gap-4 lg:grid-cols-5">
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
                                title: 'Owner',
                                key: 'owner',
                                render: (_, ticket) => (
                                    <div className="flex items-center gap-1 text-muted-alt text-xs">
                                        {channelIcon[ticket.channel]}
                                        <span>{ticket.owner}</span>
                                    </div>
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

                <LemonCard className="lg:col-span-2" hoverEffect={false}>
                    <div className="mb-3">
                        <h3 className="text-lg font-semibold">Recent content & guidance changes</h3>
                        <p className="text-sm text-muted-alt">What the AI learned or had toggled in the last 24h.</p>
                    </div>
                    <div className="space-y-3">
                        {configChanges.map((change) => (
                            <div key={change.id}>
                                <div className="flex items-center gap-2 text-sm">
                                    <LemonTag
                                        type={
                                            change.type === 'guidance'
                                                ? 'success'
                                                : change.type === 'channel'
                                                  ? 'warning'
                                                  : 'default'
                                        }
                                        size="small"
                                    >
                                        {change.type}
                                    </LemonTag>
                                    <span className="font-medium">{change.actor}</span>
                                    <span className="text-muted-alt text-xs">{change.timestamp}</span>
                                </div>
                                <div className="text-muted-alt text-sm">{change.description}</div>
                                <LemonDivider dashed className="my-3" />
                            </div>
                        ))}
                    </div>
                </LemonCard>
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
                                <div key={ticket.id} className="rounded border border-light px-3 py-2">
                                    <div className="flex items-center justify-between text-sm font-medium">
                                        <span>{ticket.subject}</span>
                                        <span className="text-xs text-muted-alt">{ticket.minutesOpen} min</span>
                                    </div>
                                    <div className="mt-1 flex items-center gap-2 text-xs text-muted-alt">
                                        <IconClock />
                                        <span>{ticket.customer}</span>
                                        <LemonTag size="small" type="muted">
                                            {ticket.channel}
                                        </LemonTag>
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
