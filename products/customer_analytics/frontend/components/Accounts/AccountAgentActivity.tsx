import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { LemonSkeleton, LemonTable, LemonTag } from '@posthog/lemon-ui'
import { type Series, TimeSeriesBarChart } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'

import type {
    AccountAgentActivityClient,
    AccountAgentActivityIntent,
    AccountAgentActivityResult,
    AccountAgentActivityTool,
} from '~/queries/schema/schema-general'

import {
    formatAgentActivityShare,
    getAgentActivityProductLabel,
    getAgentActivitySummary,
} from '../ProductActivity/agentActivityPresentation'
import { AccountsEvents } from './constants'

const EMPTY_MESSAGES: Record<string, string> = {
    no_group_type: 'Choose an account group type in Customer analytics settings to see agent activity here.',
    no_external_id: "This account isn't linked to any activity yet.",
}

const ACCESS_TAGS: Record<
    AccountAgentActivityTool['access'],
    { label: string; type: 'highlight' | 'warning' | 'muted' }
> = {
    read: { label: 'Read', type: 'highlight' },
    write: { label: 'Write', type: 'warning' },
    other: { label: 'Other', type: 'muted' },
}

const handleChartError = (error: Error): void => {
    posthog.captureException(error, { scope: 'AccountAgentActivity' })
}

function AgentStat({ label, value, description }: { label: string; value: string; description: string }): JSX.Element {
    return (
        <div className="border rounded p-3 min-w-0" title={description}>
            <div className="text-xs text-secondary truncate">{label}</div>
            <div className="text-xl font-semibold">{value}</div>
        </div>
    )
}

function AgentTrend({ result }: { result: AccountAgentActivityResult }): JSX.Element {
    const theme = useChartTheme()
    const labels = useMemo(() => result.buckets.map((bucket) => bucket.column), [result.buckets])
    const series = useMemo<Series[]>(
        () => [
            { key: 'agent', label: 'Agent calls', data: result.buckets.map((bucket) => bucket.agentCalls) },
            { key: 'ui', label: 'App pageviews', data: result.buckets.map((bucket) => bucket.uiPageviews) },
        ],
        [result.buckets]
    )
    const { timezone } = useValues(teamLogic)
    const config = useMemo(
        () => ({ xAxis: { timezone, interval: 'week' as const }, yAxis: { showGrid: true }, legend: { show: true } }),
        [timezone]
    )
    return (
        <div className="h-56 flex flex-col" data-attr="account-agent-activity-trend">
            <TimeSeriesBarChart
                series={series}
                labels={labels}
                theme={theme}
                config={config}
                onError={handleChartError}
            />
        </div>
    )
}

function ClientShare({ share }: { share: number }): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <div className="h-1.5 flex-1 rounded-full bg-surface-secondary overflow-hidden">
                {/* Width follows the data, so it can't be a Tailwind class. */}
                <div className="h-full rounded-full bg-accent" style={{ width: `${Math.round(share * 100)}%` }} />
            </div>
            <span className="text-xs text-secondary w-8 text-right">{formatAgentActivityShare(share)}</span>
        </div>
    )
}

function SectionTitle({ title, description }: { title: string; description: string }): JSX.Element {
    return (
        <div>
            <h4 className="mb-0">{title}</h4>
            <p className="text-secondary text-xs mb-0">{description}</p>
        </div>
    )
}

export function AccountAgentActivity({
    result,
    loading,
}: {
    result: AccountAgentActivityResult
    loading?: boolean
}): JSX.Element {
    const summary = getAgentActivitySummary(result)
    const { totals } = result

    if (loading && !result.buckets.length) {
        return <LemonSkeleton className="h-64 w-full" />
    }
    if (result.emptyReason) {
        return <p className="text-secondary px-4 mb-0">{EMPTY_MESSAGES[result.emptyReason]}</p>
    }
    if (!totals.agentCalls) {
        return (
            <p className="text-secondary px-4 mb-0" data-attr="account-agent-activity-empty">
                No AI agent activity for this account in the last {result.columns.length} weeks.
            </p>
        )
    }

    return (
        <div
            className={`flex flex-col gap-5 px-2 pb-2 min-w-0 ${loading ? 'opacity-50' : ''}`}
            data-attr="account-agent-activity"
        >
            <div className="@container">
                <div className="grid grid-cols-2 @lg:grid-cols-3 @4xl:grid-cols-6 gap-2">
                    <AgentStat
                        label="Agent calls"
                        value={humanFriendlyNumber(totals.agentCalls)}
                        description="MCP tool calls made for this account."
                    />
                    <AgentStat
                        label="People using agents"
                        value={humanFriendlyNumber(totals.agentPeople)}
                        description="People with at least one MCP tool call."
                    />
                    <AgentStat
                        label="Conversations"
                        value={humanFriendlyNumber(totals.conversations)}
                        description="Agent conversations with at least one MCP tool call."
                    />
                    <AgentStat
                        label="Agent share"
                        value={formatAgentActivityShare(summary.agentShare)}
                        description="Agent calls as a share of agent calls plus pageviews in the app."
                    />
                    <AgentStat
                        label="Writes"
                        value={formatAgentActivityShare(summary.writeShare)}
                        description={`${humanFriendlyNumber(totals.writes)} calls changed data and ${humanFriendlyNumber(totals.reads)} only read it.`}
                    />
                    <AgentStat
                        label="Error rate"
                        value={formatAgentActivityShare(summary.errorRate)}
                        description="Agent calls that returned an error."
                    />
                </div>
            </div>
            <AgentTrend result={result} />
            <div className="flex flex-col gap-2">
                <SectionTitle
                    title="What agents do"
                    description="Calls by product and tool. Calls through exec count toward the tool they ran."
                />
                <LemonTable<AccountAgentActivityTool>
                    size="small"
                    dataSource={result.tools}
                    rowKey={(tool) => `${tool.product}:${tool.tool}`}
                    pagination={{ pageSize: 10 }}
                    columns={[
                        {
                            title: 'Product',
                            key: 'product',
                            render: (_, tool) => getAgentActivityProductLabel(result, tool.product),
                        },
                        {
                            title: 'Tool',
                            key: 'tool',
                            render: (_, tool) => <span className="font-mono text-xs break-all">{tool.tool}</span>,
                        },
                        {
                            title: 'Access',
                            key: 'access',
                            render: (_, tool) => (
                                <LemonTag type={ACCESS_TAGS[tool.access].type}>
                                    {ACCESS_TAGS[tool.access].label}
                                </LemonTag>
                            ),
                        },
                        { title: 'Calls', dataIndex: 'calls', align: 'right', sorter: (a, b) => a.calls - b.calls },
                        { title: 'People', dataIndex: 'people', align: 'right', sorter: (a, b) => a.people - b.people },
                        {
                            title: 'Conversations',
                            dataIndex: 'conversations',
                            align: 'right',
                            sorter: (a, b) => a.conversations - b.conversations,
                        },
                        {
                            title: 'Errors',
                            key: 'errors',
                            align: 'right',
                            render: (_, tool) =>
                                tool.errors ? formatAgentActivityShare(tool.errors / tool.calls) : '-',
                            sorter: (a, b) => a.errors / a.calls - b.errors / b.calls,
                        },
                    ]}
                />
            </div>
            <div className="flex flex-col gap-2 min-w-0">
                <SectionTitle title="Top clients" description="MCP clients by calls." />
                <LemonTable<AccountAgentActivityClient>
                    size="small"
                    dataSource={result.clients}
                    rowKey="name"
                    emptyState="The calls didn't name a client."
                    columns={[
                        { title: 'Client', dataIndex: 'name' },
                        {
                            title: 'Share of calls',
                            key: 'share',
                            width: '40%',
                            render: (_, client) => <ClientShare share={client.calls / totals.agentCalls} />,
                        },
                        { title: 'Calls', dataIndex: 'calls', align: 'right' },
                        { title: 'People', dataIndex: 'people', align: 'right' },
                    ]}
                />
            </div>
            <div className="flex flex-col gap-2 min-w-0">
                <SectionTitle
                    title="Top intents"
                    description="What agents said they were doing, grouped by exact text."
                />
                <LemonTable<AccountAgentActivityIntent>
                    size="small"
                    dataSource={result.intents}
                    rowKey="intent"
                    emptyState="The calls didn't include an intent."
                    expandable={{
                        expandedRowRender: (intent) => (
                            <p className="whitespace-pre-wrap break-words mb-0 px-2 py-1">{intent.intent}</p>
                        ),
                        onRowExpand: () => posthog.capture(AccountsEvents.AgentActivityIntentExpanded),
                    }}
                    columns={[
                        {
                            title: 'Intent',
                            key: 'intent',
                            render: (_, intent) => <span className="line-clamp-2 break-words">{intent.intent}</span>,
                        },
                        { title: 'Calls', dataIndex: 'calls', align: 'right' },
                        { title: 'Conversations', dataIndex: 'conversations', align: 'right' },
                        {
                            title: 'Last seen',
                            key: 'lastSeen',
                            render: (_, intent) => <TZLabel time={intent.lastSeen} />,
                        },
                    ]}
                />
            </div>
        </div>
    )
}
