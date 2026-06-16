/**
 * Agents list — the landing page.
 *
 * Layout: single column, full-width agent list under a fleet-level
 * StatStrip. Each row carries its own stats (live · sessions 24h ·
 * failed · spend · last activity) so the operator can sweep down the
 * list and triage without opening individual agents.
 */

import { ChevronRightIcon } from 'lucide-react'
import { useMemo, useState } from 'react'

import type { AgentApplicationFixture, AgentStats, FleetStats } from '@posthog/agent-chat/fixtures'

import { EditWithAIButton } from '@/components/EditWithAIButton'
import { FilterChips } from '@/components/FilterChips'
import { StatStrip, type StatTile } from '@/components/StatStrip'

const FILTERS = ['all', 'live', 'drafts', 'archived'] as const
type Filter = (typeof FILTERS)[number]

export interface AgentsListProps {
    agents: AgentApplicationFixture[]
    /** Fleet rollup for the top StatStrip. */
    fleetStats: FleetStats
    /** Per-agent rollup keyed by agent slug. Missing entries render the row without stats. */
    statsBySlug?: Record<string, AgentStats>
    onOpenAgent?: (slug: string) => void
}

export function AgentsList({ agents, fleetStats, statsBySlug = {}, onOpenAgent }: AgentsListProps): React.ReactElement {
    const [filter, setFilter] = useState<Filter>('all')

    const tiles = useMemo<StatTile[]>(
        () => [
            { label: 'Agents', value: agents.length, hint: 'in this project' },
            { label: 'Live now', value: fleetStats.liveSessionCount, hint: 'sessions in flight' },
            { label: 'Sessions · 24h', value: fleetStats.sessions24hCount.toLocaleString(), hint: 'across all agents' },
            {
                label: 'Spend · 24h',
                value: `$${fleetStats.spend24hUsd.toFixed(2)}`,
                hint:
                    fleetStats.approvalsPendingCount > 0
                        ? `${fleetStats.approvalsPendingCount} approval${fleetStats.approvalsPendingCount === 1 ? '' : 's'} pending`
                        : 'rolling',
                tone: fleetStats.approvalsPendingCount > 0 ? 'attention' : 'default',
            },
        ],
        [agents.length, fleetStats]
    )

    const filteredAgents = useMemo(() => {
        switch (filter) {
            case 'live':
                return agents.filter((a) => !a.archived && (statsBySlug[a.slug]?.liveCount ?? 0) > 0)
            case 'drafts':
                return agents.filter((a) => !a.archived && !a.live_revision)
            case 'archived':
                return agents.filter((a) => a.archived)
            case 'all':
            default:
                return agents.filter((a) => !a.archived)
        }
    }, [agents, filter, statsBySlug])

    return (
        <div className="mx-auto max-w-6xl px-6 py-6">
            <header className="mb-4 flex items-end justify-between">
                <div>
                    <h1 className="text-xl font-medium tracking-tight">Agents</h1>
                    <p className="text-sm text-muted-foreground">
                        {agents.length === 0 ? 'None yet.' : `${agents.length} in this project.`}
                    </p>
                </div>
                <EditWithAIButton prompt="Help me create a new agent." label="New agent with AI" />
            </header>

            <StatStrip tiles={tiles} className="mb-4" />

            {agents.length === 0 ? (
                <EmptyState />
            ) : (
                <div className="min-w-0">
                    <div className="mb-3 flex items-center justify-between">
                        <FilterChips
                            options={FILTERS}
                            value={filter}
                            onChange={setFilter}
                            labels={{
                                all: 'All',
                                live: 'Live',
                                drafts: 'Drafts',
                                archived: 'Archived',
                            }}
                        />
                        <span className="text-[0.6875rem] text-muted-foreground">
                            {filteredAgents.length} of {agents.length}
                        </span>
                    </div>

                    {filteredAgents.length === 0 ? (
                        <NoMatches filter={filter} />
                    ) : (
                        <ul className="divide-y divide-border rounded-md border border-border bg-card">
                            {filteredAgents.map((agent) => (
                                <li key={agent.id}>
                                    <AgentRow agent={agent} stats={statsBySlug[agent.slug]} onOpenAgent={onOpenAgent} />
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            )}
        </div>
    )
}

function AgentRow({
    agent,
    stats,
    onOpenAgent,
}: {
    agent: AgentApplicationFixture
    stats: AgentStats | undefined
    onOpenAgent?: (slug: string) => void
}): React.ReactElement {
    const status = statusOf(agent)
    const failureRate = stats?.failureRate24h
    const failedCount =
        stats && stats.sessions24hCount > 0 && failureRate !== undefined
            ? Math.round(failureRate * stats.sessions24hCount)
            : 0
    const liveCount = stats?.liveCount ?? 0
    const lastActivityIso = stats?.lastActivityAt ?? agent.updated_at

    return (
        <button
            type="button"
            onClick={() => onOpenAgent?.(agent.slug)}
            className="group flex w-full cursor-pointer items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
        >
            <span className={`mt-1.5 inline-flex h-1.5 w-1.5 shrink-0 rounded-full ${status.dotClass}`} aria-hidden />

            {/* flex-wrap so stats drop below the name/description when the
                row gets too narrow to keep both inline. basis-72 keeps the
                left half from collapsing to a single-word column. */}
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-2">
                <div className="min-w-0 flex-1 basis-72">
                    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                        <span className="truncate text-sm font-medium group-hover:text-foreground">{agent.name}</span>
                        <code className="truncate text-[0.6875rem] text-muted-foreground">{agent.slug}</code>
                        <span className="text-[0.6875rem] text-muted-foreground">· {status.label}</span>
                    </div>
                    <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">{agent.description}</p>
                </div>

                {/* Stats group is shrink-0 so columns never compress; whole
                    group wraps as a unit when there isn't horizontal room. */}
                <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 text-[0.6875rem] text-muted-foreground">
                    <StatColumn
                        label="Live"
                        value={liveCount > 0 ? `${liveCount}` : '—'}
                        valueClass={liveCount > 0 ? 'text-info-foreground' : undefined}
                        accent={
                            liveCount > 0 ? (
                                <span
                                    className="inline-flex h-1 w-1 animate-pulse rounded-full bg-info-foreground"
                                    aria-hidden
                                />
                            ) : null
                        }
                    />
                    <StatColumn
                        label="24h"
                        value={stats ? stats.sessions24hCount.toLocaleString() : '—'}
                        valueClass={stats?.sessions24hCount ? 'text-foreground' : undefined}
                    />
                    <StatColumn
                        label="Failed"
                        value={failedCount > 0 ? `${failedCount}` : '—'}
                        valueClass={failedCount > 0 ? 'text-destructive-foreground' : undefined}
                        sub={
                            failedCount > 0 && failureRate !== undefined
                                ? `${Math.round(failureRate * 100)}%`
                                : undefined
                        }
                    />
                    <StatColumn
                        label="Spend"
                        value={stats ? `$${stats.spend24hUsd.toFixed(2)}` : '—'}
                        valueClass={stats && stats.spend24hUsd > 0 ? 'text-foreground' : undefined}
                    />
                    <StatColumn label="Last run" value={formatRelative(lastActivityIso)} />
                </div>
            </div>

            <ChevronRightIcon className="mt-1.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/60 transition-all group-hover:translate-x-0.5 group-hover:text-foreground" />
        </button>
    )
}

function StatColumn({
    label,
    value,
    valueClass,
    sub,
    accent,
}: {
    label: string
    value: string
    valueClass?: string
    /** Optional small line under the label — used for the failed-rate %. */
    sub?: string
    accent?: React.ReactNode
}): React.ReactElement {
    return (
        <div className="flex min-w-16 flex-col items-end gap-0.5 whitespace-nowrap tabular-nums">
            <div className={`flex items-center gap-1 text-xs font-medium ${valueClass ?? 'text-muted-foreground'}`}>
                {accent}
                <span>{value}</span>
                {sub ? <span className="text-[0.625rem] text-muted-foreground/80">{sub}</span> : null}
            </div>
            <span className="text-[0.625rem] uppercase tracking-wide text-muted-foreground/70">{label}</span>
        </div>
    )
}

function EmptyState(): React.ReactElement {
    return (
        <div className="rounded-md border border-dashed border-border p-8 text-center">
            <p className="text-sm font-medium">No agents yet</p>
            <p className="mt-1 text-xs text-muted-foreground">
                Agents run on triggers and act on your data. The concierge will walk you through your first one.
            </p>
            <div className="mt-4 flex justify-center">
                <EditWithAIButton prompt="Help me create a new agent." label="New agent with AI" />
            </div>
        </div>
    )
}

function NoMatches({ filter }: { filter: Filter }): React.ReactElement {
    const message =
        filter === 'live'
            ? 'No agents have running sessions right now.'
            : filter === 'drafts'
              ? 'No drafts pending promotion.'
              : filter === 'archived'
                ? 'No archived agents.'
                : 'No matching agents.'
    return (
        <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
            {message}
        </div>
    )
}

function statusOf(agent: AgentApplicationFixture): { dotClass: string; label: string } {
    if (agent.archived) {
        return { dotClass: 'bg-muted-foreground/40', label: 'Archived' }
    }
    if (agent.live_revision) {
        return { dotClass: 'bg-success-foreground', label: 'Live' }
    }
    return { dotClass: 'bg-warning-foreground', label: 'Draft' }
}

function formatRelative(iso: string): string {
    const then = new Date(iso).getTime()
    if (!then) {
        return '—'
    }
    const diff = Math.max(0, Date.now() - then)
    const minute = 60 * 1000
    const hour = 60 * minute
    const day = 24 * hour
    if (diff < minute) {
        return 'just now'
    }
    if (diff < hour) {
        return `${Math.floor(diff / minute)}m ago`
    }
    if (diff < day) {
        return `${Math.floor(diff / hour)}h ago`
    }
    return `${Math.floor(diff / day)}d ago`
}
