import { useMemo } from 'react'

import { LemonCard, LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ScenesTabs } from '../../components/ScenesTabs'

const containmentTrend = [
    { period: 'Mon', overall: 68, widget: 72, slack: 61, email: 77 },
    { period: 'Tue', overall: 71, widget: 75, slack: 63, email: 80 },
    { period: 'Wed', overall: 74, widget: 78, slack: 66, email: 83 },
    { period: 'Thu', overall: 73, widget: 76, slack: 64, email: 84 },
    { period: 'Fri', overall: 76, widget: 81, slack: 67, email: 85 },
    { period: 'Sat', overall: 79, widget: 83, slack: 70, email: 86 },
    { period: 'Sun', overall: 78, widget: 84, slack: 68, email: 82 },
]

const escalationReasons = [
    { reason: 'Policy / compliance', count: 45, trend: 6 },
    { reason: 'Priority customer', count: 29, trend: -4 },
    { reason: 'Integration failure', count: 22, trend: 2 },
    { reason: 'AI low confidence', count: 19, trend: 0 },
]

const channelVolume = [
    { channel: 'Widget', total: 322, ai: 212, human: 110 },
    { channel: 'Slack connect', total: 184, ai: 96, human: 88 },
    { channel: 'Email', total: 128, ai: 92, human: 36 },
]

const csatLeaderboard = [
    { owner: 'AI Assist', csat: 4.4, containRate: 0.78 },
    { owner: 'Dana Hill', csat: 4.8, containRate: 0.0 },
    { owner: 'Priya K', csat: 4.6, containRate: 0.0 },
    { owner: 'Support bot', csat: 4.2, containRate: 0.65 },
]

export const scene: SceneExport = {
    component: ConversationsAnalyticsScene,
}

export function ConversationsAnalyticsScene(): JSX.Element {
    const trendOptions = useMemo(
        () => [
            { value: 'overall', label: 'Overall' },
            { value: 'widget', label: 'Widget' },
            { value: 'slack', label: 'Slack' },
            { value: 'email', label: 'Email' },
        ],
        []
    )

    return (
        <SceneContent className="space-y-5">
            <ScenesTabs />
            <section className="space-y-1">
                <h1 className="text-2xl font-semibold">Resolution analytics</h1>
                <p className="text-muted-alt">
                    Track AI containment, escalation reasons, SLA breaches, and agent vs AI performance.
                </p>
            </section>

            <div className="grid gap-4 lg:grid-cols-3">
                <LemonCard hoverEffect={false} className="lg:col-span-2">
                    <div className="mb-3 flex items-center justify-between">
                        <div>
                            <h3 className="text-lg font-semibold">AI containment trend</h3>
                            <p className="text-sm text-muted-alt">Compare containment on key channels over time.</p>
                        </div>
                        <LemonSelect value="overall" options={trendOptions} placeholder="Channel" />
                    </div>
                    <div className="rounded border border-dashed border-light bg-bg-300 p-4 text-center text-muted-alt">
                        Line chart placeholder showing {containmentTrend.length} data points
                    </div>
                </LemonCard>

                <LemonCard hoverEffect={false}>
                    <h3 className="text-lg font-semibold">SLA breaches</h3>
                    <p className="text-sm text-muted-alt">SLA promise: 60 min. Trend vs last week.</p>
                    <div className="mt-4 flex flex-col gap-2">
                        <div className="flex justify-between text-sm">
                            <span>Breaches (24h)</span>
                            <span className="text-danger font-semibold">6 (+1)</span>
                        </div>
                        <div className="flex justify-between text-sm">
                            <span>At risk now</span>
                            <span className="text-warning font-semibold">12</span>
                        </div>
                        <div className="flex justify-between text-sm">
                            <span>Median resolution time</span>
                            <span className="font-semibold">42 min</span>
                        </div>
                        <div className="flex justify-between text-sm">
                            <span>Median time to first response</span>
                            <span className="font-semibold">2m 04s</span>
                        </div>
                    </div>
                </LemonCard>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
                <LemonCard hoverEffect={false}>
                    <div className="mb-3">
                        <h3 className="text-lg font-semibold">Escalation reasons</h3>
                        <p className="text-sm text-muted-alt">Top fallback triggers, with week-over-week change.</p>
                    </div>
                    <LemonTable
                        dataSource={escalationReasons}
                        rowKey="reason"
                        columns={[
                            {
                                title: 'Reason',
                                dataIndex: 'reason',
                            },
                            {
                                title: 'Escalations (7d)',
                                dataIndex: 'count',
                                align: 'right',
                            },
                            {
                                title: 'Trend',
                                key: 'trend',
                                align: 'right',
                                render: (_, row) => (
                                    <LemonTag type={row.trend >= 0 ? 'warning' : 'success'}>
                                        {row.trend >= 0 ? '+' : ''}
                                        {row.trend}
                                    </LemonTag>
                                ),
                            },
                        ]}
                    />
                </LemonCard>

                <LemonCard hoverEffect={false}>
                    <div className="mb-3">
                        <h3 className="text-lg font-semibold">Containment by channel</h3>
                        <p className="text-sm text-muted-alt">Ticket volume vs AI containment by source.</p>
                    </div>
                    <LemonTable
                        dataSource={channelVolume}
                        rowKey="channel"
                        columns={[
                            {
                                title: 'Channel',
                                dataIndex: 'channel',
                            },
                            {
                                title: 'Tickets',
                                dataIndex: 'total',
                                align: 'right',
                            },
                            {
                                title: 'AI-contained',
                                dataIndex: 'ai',
                                align: 'right',
                            },
                            {
                                title: 'Human',
                                dataIndex: 'human',
                                align: 'right',
                            },
                        ]}
                    />
                </LemonCard>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
                <LemonCard hoverEffect={false}>
                    <div className="mb-3 flex items-center justify-between">
                        <h3 className="text-lg font-semibold">AI vs human CSAT</h3>
                        <p className="text-sm text-muted-alt">Leaderboard for containment agents and humans.</p>
                    </div>
                    <LemonTable
                        dataSource={csatLeaderboard}
                        rowKey="owner"
                        columns={[
                            {
                                title: 'Owner',
                                dataIndex: 'owner',
                            },
                            {
                                title: 'CSAT',
                                dataIndex: 'csat',
                                align: 'right',
                            },
                            {
                                title: 'Containment',
                                key: 'containRate',
                                align: 'right',
                                render: (_, row) => `${Math.round(row.containRate * 100)}%`,
                            },
                        ]}
                    />
                </LemonCard>

                <div className="rounded border border-dashed border-light bg-bg-300 p-4 text-center text-muted-alt">
                    Placeholder for SLA funnel chart (Touchpoint: AI → human → resolution)
                </div>
            </div>
        </SceneContent>
    )
}
