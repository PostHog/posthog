/**
 * Overview — the new landing page.
 *
 * The screen leads with the concierge chat embedded inline so a fresh
 * visitor can just start talking — no "click the side panel first" step.
 * Below the chat sits a compact set of starter prompts (clicking one
 * seeds the concierge) and a handful of quick-link tiles into the
 * other top-level surfaces.
 *
 * The chat itself isn't rendered by this screen — it's portaled in via
 * `useDockEmbedSlot()` so the same `<Dock />` instance owns its runner
 * across navigation (start a thread here, keep talking in the side dock
 * after navigating to /agents).
 */

'use client'

import { BotIcon, LibraryIcon, SparklesIcon, WalletIcon } from 'lucide-react'
import Link from 'next/link'
import { useMemo } from 'react'

import type { FleetStats } from '@posthog/agent-chat/fixtures'

import { useDockStore } from '@/components/dock-context'
import { StatStrip, type StatTile } from '@/components/StatStrip'
import { useDockEmbedSlot } from '@/lib/useDockLayout'

interface StarterPrompt {
    label: string
    prompt: string
}

const DEFAULT_PROMPTS: StarterPrompt[] = [
    { label: 'Create a new agent', prompt: 'Help me create a new agent.' },
    { label: 'Show me my agents', prompt: 'Give me a quick rundown of the agents I have today.' },
    { label: "What's happening right now?", prompt: 'What sessions are running right now across my agents?' },
    { label: 'Review my spend', prompt: 'How is my agent spend looking this week and where is it going?' },
]

export interface OverviewProps {
    /** User's first name for the greeting. Falls back to a generic line. */
    displayName?: string | null
    /** Optional fleet stats summary — when present, shown as a small strip beneath the prompts. */
    fleetStats?: FleetStats | null
    /** Optional agent count for the stat strip. */
    agentCount?: number
}

export function Overview({ displayName, fleetStats, agentCount }: OverviewProps): React.ReactElement {
    const embedRef = useDockEmbedSlot()
    const { startConcierge } = useDockStore()

    const greeting = displayName ? `Hi ${displayName}.` : 'Welcome back.'

    const stats = useMemo<StatTile[] | null>(() => {
        if (!fleetStats) {
            return null
        }
        return [
            { label: 'Agents', value: agentCount ?? '—', hint: 'in this project' },
            { label: 'Live now', value: fleetStats.liveSessionCount, hint: 'sessions in flight' },
            {
                label: 'Sessions · 24h',
                value: fleetStats.sessions24hCount.toLocaleString(),
                hint: 'across all agents',
            },
            {
                label: 'Spend · 24h',
                value: `$${fleetStats.spend24hUsd.toFixed(2)}`,
                hint:
                    fleetStats.approvalsPendingCount > 0
                        ? `${fleetStats.approvalsPendingCount} approval${fleetStats.approvalsPendingCount === 1 ? '' : 's'} pending`
                        : 'rolling',
                tone: fleetStats.approvalsPendingCount > 0 ? 'attention' : 'default',
            },
        ]
    }, [agentCount, fleetStats])

    return (
        <div className="mx-auto flex h-full w-full max-w-5xl flex-col gap-6 px-6 py-6">
            <header className="flex flex-col gap-1">
                <h1 className="text-xl font-medium tracking-tight">{greeting}</h1>
                <p className="text-sm text-muted-foreground">What do you want to do?</p>
            </header>

            {/* Embedded chat — the Dock portals into this node. The min-h
             *  keeps a useful default size on tall viewports; the dock's
             *  own layout fills whatever space we give it. */}
            <div
                ref={embedRef}
                className="min-h-[420px] flex-1 overflow-hidden rounded-lg border border-border bg-card shadow-sm"
            />

            {/* Starter prompts — clicking one seeds the concierge via the
             *  same `startConcierge` path `<EditWithAIButton>` uses. */}
            <section aria-labelledby="overview-prompts">
                <h2
                    id="overview-prompts"
                    className="mb-2 text-[0.6875rem] uppercase tracking-wide text-muted-foreground"
                >
                    Try asking
                </h2>
                <div className="flex flex-wrap gap-2">
                    {DEFAULT_PROMPTS.map((p) => (
                        <button
                            key={p.label}
                            type="button"
                            onClick={() => startConcierge({ prompt: p.prompt })}
                            className="inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-foreground/30 hover:bg-accent"
                            title={p.prompt}
                        >
                            <SparklesIcon className="h-3 w-3 text-muted-foreground" aria-hidden />
                            {p.label}
                        </button>
                    ))}
                </div>
            </section>

            {stats ? <StatStrip tiles={stats} size="sm" /> : null}

            <section aria-labelledby="overview-jump-to" className="pb-2">
                <h2
                    id="overview-jump-to"
                    className="mb-2 text-[0.6875rem] uppercase tracking-wide text-muted-foreground"
                >
                    Jump to
                </h2>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                    <JumpCard
                        href="/agents"
                        icon={<BotIcon className="h-4 w-4" aria-hidden />}
                        title="Agents"
                        subtitle={agentCount != null ? `${agentCount} in this project` : 'Browse the fleet'}
                    />
                    <JumpCard
                        href="/registry"
                        icon={<LibraryIcon className="h-4 w-4" aria-hidden />}
                        title="Tools & skills"
                        subtitle="Shared building blocks"
                    />
                    <JumpCard
                        href="/billing"
                        icon={<WalletIcon className="h-4 w-4" aria-hidden />}
                        title="Billing"
                        subtitle="Wallet and spend"
                    />
                </div>
            </section>
        </div>
    )
}

function JumpCard({
    href,
    icon,
    title,
    subtitle,
}: {
    href: string
    icon: React.ReactNode
    title: string
    subtitle: string
}): React.ReactElement {
    return (
        <Link
            href={href}
            className="group flex cursor-pointer items-center gap-3 rounded-md border border-border bg-card px-3 py-2 transition-colors hover:border-foreground/30 hover:bg-accent"
        >
            <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground group-hover:text-foreground">
                {icon}
            </span>
            <div className="min-w-0">
                <div className="text-sm font-medium leading-tight">{title}</div>
                <div className="truncate text-xs text-muted-foreground">{subtitle}</div>
            </div>
        </Link>
    )
}
