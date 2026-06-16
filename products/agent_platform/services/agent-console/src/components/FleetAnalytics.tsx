/**
 * Fleet analytics — a cross-agent dashboard over the agents' `$ai_*` events
 * (captured into this team's own project by the runner). Top-line KPIs with
 * 14-day sparklines + WoW deltas, spend-by-agent and cost-by-model bar charts,
 * and per-agent + tool-reliability tables. Charts come from `@posthog/quill-charts`
 * so it reads like the rest of PostHog.
 *
 * Pure presentation — `analytics-client` runs the HogQL + shapes the data.
 */

'use client'

import { AlertTriangleIcon, ArrowDownIcon, ArrowUpIcon, LineChartIcon } from 'lucide-react'

import { BarChart, useChartTheme } from '@posthog/quill-charts'

import type { AgentRow, FleetAnalyticsData, ModelRow, ToolRow } from '@/lib/fleetAnalytics'

export interface FleetAnalyticsProps {
    data: FleetAnalyticsData
    /** `fleet` shows the by-agent breakdown; `agent` drops it (already scoped to one). */
    scope?: 'fleet' | 'agent'
    title?: string
    subtitle?: string
    /** Deep link to the full AI observability product (agent-filtered in agent scope). */
    aiObservabilityUrl?: string
    /** Skeleton while the first load is in flight (polled refreshes don't flip this). */
    loading?: boolean
    /** Set when the load failed outright — renders an error state instead of "no data". */
    error?: string | null
}

const usd = (v: number): string => (v >= 100 ? `$${v.toFixed(0)}` : `$${v.toFixed(2)}`)
const pct = (v: number): string => `${(v * 100).toFixed(1)}%`
const secs = (v: number): string => `${v.toFixed(v < 10 ? 1 : 0)}s`
const int = (v: number): string => v.toLocaleString()

export function FleetAnalytics({
    data,
    scope = 'fleet',
    title = 'Analytics',
    subtitle = 'Across all agents · last 7 days (14-day trend)',
    aiObservabilityUrl,
    loading,
    error,
}: FleetAnalyticsProps): React.ReactElement {
    const isFleet = scope === 'fleet'
    return (
        <div className="mx-auto max-w-6xl space-y-5 px-6 pb-10 pt-5">
            <header className="flex items-end justify-between">
                <div>
                    <h1 className="text-lg font-semibold text-foreground">{title}</h1>
                    <p className="text-xs text-muted-foreground">{subtitle}</p>
                </div>
                {aiObservabilityUrl ? (
                    <a
                        href={aiObservabilityUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
                    >
                        <LineChartIcon className="h-3.5 w-3.5" aria-hidden />
                        Open in AI observability ↗
                    </a>
                ) : null}
            </header>

            {loading ? (
                <LoadingSkeleton />
            ) : error ? (
                <ErrorState message={error} />
            ) : data.empty ? (
                <EmptyState />
            ) : (
                <>
                    <KpiRow data={data} />
                    {isFleet ? (
                        <>
                            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                                <Panel title="Spend by agent">
                                    <SpendByAgentChart rows={data.byAgent} />
                                </Panel>
                                <Panel title="Cost by model">
                                    <CostByModelChart rows={data.byModel} />
                                </Panel>
                            </div>
                            <Panel title="Agents">
                                <AgentsTable rows={data.byAgent} />
                            </Panel>
                        </>
                    ) : (
                        <Panel title="Cost by model">
                            <CostByModelChart rows={data.byModel} />
                        </Panel>
                    )}
                    <Panel title="Tool reliability">
                        <ToolTable rows={data.toolErrors} />
                    </Panel>
                </>
            )}
        </div>
    )
}

/* ── KPIs ─────────────────────────────────────────────────────────── */

function KpiRow({ data }: { data: FleetAnalyticsData }): React.ReactElement {
    const { kpis, deltas } = data
    return (
        <div className="grid grid-cols-2 gap-0 overflow-hidden rounded-md border border-border bg-card sm:grid-cols-4">
            <KpiTile i={0} label="Spend · 7d" value={usd(kpis.spendUsd)} delta={deltas.spend} goodDirection="down" />
            <KpiTile
                i={1}
                label="Sessions · 7d"
                value={int(kpis.sessions)}
                delta={deltas.sessions}
                goodDirection="up"
            />
            <KpiTile
                i={2}
                label="Failure rate · 7d"
                value={pct(kpis.failureRate)}
                delta={deltas.failureRatePoints}
                deltaUnit="pp"
                goodDirection="down"
                attention={kpis.failureRate > 0}
            />
            <KpiTile i={3} label="p95 latency · 7d" value={secs(kpis.p95LatencyS)} />
        </div>
    )
}

function KpiTile({
    i,
    label,
    value,
    delta,
    deltaUnit = '%',
    goodDirection,
    attention,
}: {
    i: number
    label: string
    value: string
    delta?: number | null
    deltaUnit?: '%' | 'pp'
    goodDirection?: 'up' | 'down'
    attention?: boolean
}): React.ReactElement {
    const hasDelta = delta != null && Number.isFinite(delta) && goodDirection != null
    return (
        <div
            className={
                'px-4 py-3' +
                (i > 0 ? ' border-l border-border' : '') +
                (i >= 2 ? ' border-t border-border sm:border-t-0' : '')
            }
        >
            <div className="text-[0.6875rem] uppercase tracking-wide text-muted-foreground">{label}</div>
            <div className="mt-1 flex items-baseline gap-2">
                <span
                    className={
                        'font-mono text-xl leading-tight tabular-nums ' +
                        (attention ? 'text-warning-foreground' : 'text-foreground')
                    }
                >
                    {value}
                </span>
                {hasDelta ? <DeltaChip value={delta!} unit={deltaUnit} goodDirection={goodDirection!} /> : null}
            </div>
            <div className="mt-0.5 text-[0.6875rem] text-muted-foreground">{hasDelta ? 'vs prior 7d' : ' '}</div>
        </div>
    )
}

function DeltaChip({
    value,
    unit,
    goodDirection,
}: {
    value: number
    unit: '%' | 'pp'
    goodDirection: 'up' | 'down'
}): React.ReactElement {
    const up = value >= 0
    const good = goodDirection === 'up' ? up : !up
    const Arrow = up ? ArrowUpIcon : ArrowDownIcon
    const magnitude = unit === 'pp' ? Math.abs(value).toFixed(1) : String(Math.abs(Math.round(value)))
    return (
        <span
            className={
                'inline-flex items-center gap-0.5 text-[0.6875rem] font-medium tabular-nums ' +
                (good ? 'text-success-foreground' : 'text-destructive-foreground')
            }
        >
            <Arrow className="h-3 w-3" aria-hidden />
            {magnitude}
            {unit}
        </span>
    )
}

/* ── Charts ───────────────────────────────────────────────────────── */

function SpendByAgentChart({ rows }: { rows: AgentRow[] }): React.ReactElement {
    const theme = useChartTheme()
    const top = rows.slice(0, 8)
    if (top.length === 0) {
        return <EmptyHint text="No spend recorded yet." />
    }
    return (
        <div className="h-56 w-full">
            <BarChart
                series={[{ key: 'spend', label: 'Spend (USD)', data: top.map((r) => r.spendUsd) }]}
                labels={top.map((r) => r.name)}
                config={{ axisOrientation: 'horizontal', showGrid: false }}
                theme={theme}
            />
        </div>
    )
}

function CostByModelChart({ rows }: { rows: ModelRow[] }): React.ReactElement {
    const theme = useChartTheme()
    if (rows.length === 0) {
        return <EmptyHint text="No model usage recorded yet." />
    }
    return (
        <div className="h-56 w-full">
            <BarChart
                series={[{ key: 'cost', label: 'Cost (USD)', data: rows.map((r) => r.spendUsd) }]}
                labels={rows.map((r) => r.model)}
                config={{ axisOrientation: 'horizontal', showGrid: false }}
                theme={theme}
            />
        </div>
    )
}

/* ── Tables ───────────────────────────────────────────────────────── */

function AgentsTable({ rows }: { rows: AgentRow[] }): React.ReactElement {
    if (rows.length === 0) {
        return <EmptyHint text="No agent activity in the last 7 days." />
    }
    return (
        <table className="w-full text-xs">
            <thead>
                <tr className="border-b border-border text-left text-muted-foreground">
                    <Th className="text-left">Agent</Th>
                    <Th>Sessions</Th>
                    <Th>Spend</Th>
                    <Th>Failure rate</Th>
                    <Th>p95 latency</Th>
                    <Th>Tokens</Th>
                </tr>
            </thead>
            <tbody>
                {rows.map((r) => (
                    <tr key={r.id} className="border-b border-border/50 last:border-0">
                        <td className="py-1.5 pr-2 font-medium text-foreground">{r.name}</td>
                        <Td>{int(r.sessions)}</Td>
                        <Td>{usd(r.spendUsd)}</Td>
                        <Td>
                            <span className={r.failureRate > 0 ? 'text-destructive-foreground' : 'text-foreground'}>
                                {pct(r.failureRate)}
                            </span>
                        </Td>
                        <Td>{secs(r.p95LatencyS)}</Td>
                        <Td>{int(r.tokens)}</Td>
                    </tr>
                ))}
            </tbody>
        </table>
    )
}

function ToolTable({ rows }: { rows: ToolRow[] }): React.ReactElement {
    if (rows.length === 0) {
        return <EmptyHint text="No tool calls recorded yet." />
    }
    return (
        <table className="w-full text-xs">
            <thead>
                <tr className="border-b border-border text-left text-muted-foreground">
                    <Th className="text-left">Tool</Th>
                    <Th>Calls</Th>
                    <Th>Errors</Th>
                    <Th>Error rate</Th>
                </tr>
            </thead>
            <tbody>
                {rows.map((r) => (
                    <tr key={r.tool} className="border-b border-border/50 last:border-0">
                        <td className="py-1.5 pr-2 font-mono text-foreground">{r.tool}</td>
                        <Td>{int(r.calls)}</Td>
                        <Td>{int(r.errors)}</Td>
                        <Td>
                            <span className={r.errorRate > 0 ? 'text-destructive-foreground' : 'text-foreground'}>
                                {pct(r.errorRate)}
                            </span>
                        </Td>
                    </tr>
                ))}
            </tbody>
        </table>
    )
}

/* ── Primitives ───────────────────────────────────────────────────── */

function Panel({ title, children }: { title: string; children: React.ReactNode }): React.ReactElement {
    return (
        <div className="overflow-hidden rounded-md border border-border bg-card">
            <div className="border-b border-border px-3 py-2">
                <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h3>
            </div>
            <div className="px-3 py-3">{children}</div>
        </div>
    )
}

function Th({ children, className }: { children: React.ReactNode; className?: string }): React.ReactElement {
    return <th className={`py-1.5 pr-2 font-medium ${className ?? 'text-right'}`}>{children}</th>
}

function Td({ children }: { children: React.ReactNode }): React.ReactElement {
    return <td className="py-1.5 pr-2 text-right tabular-nums text-foreground">{children}</td>
}

function EmptyHint({ text }: { text: string }): React.ReactElement {
    return <p className="text-xs italic text-muted-foreground">{text}</p>
}

function EmptyState(): React.ReactElement {
    return (
        <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border py-16 text-center">
            <LineChartIcon className="h-6 w-6 text-muted-foreground" aria-hidden />
            <p className="text-sm font-medium text-foreground">No AI activity yet</p>
            <p className="max-w-sm text-xs text-muted-foreground">
                Once your agents run, their model calls, tool spans, cost and latency show up here — and in full detail
                in AI observability.
            </p>
        </div>
    )
}

function ErrorState({ message }: { message: string }): React.ReactElement {
    return (
        <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed border-destructive/40 py-16 text-center">
            <AlertTriangleIcon className="h-6 w-6 text-destructive-foreground" aria-hidden />
            <p className="text-sm font-medium text-foreground">Couldn't load analytics</p>
            <p className="max-w-md text-xs text-muted-foreground">{message}</p>
        </div>
    )
}

/* ── Loading skeleton ─────────────────────────────────────────────── */

function LoadingSkeleton(): React.ReactElement {
    return (
        <div className="space-y-5">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                {[0, 1, 2, 3].map((i) => (
                    <Skel key={i} className="h-24" />
                ))}
            </div>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <Skel className="h-64" />
                <Skel className="h-64" />
            </div>
            <Skel className="h-40" />
            <Skel className="h-32" />
        </div>
    )
}

function Skel({ className }: { className?: string }): React.ReactElement {
    return <div className={`animate-pulse rounded-md border border-border bg-muted/40 ${className ?? ''}`} />
}
