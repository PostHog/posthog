'use client'

import { useRouter } from 'next/navigation'
import { useMemo } from 'react'

import { useAgent, useRevisions } from '@/components/agent-context'
import { AgentOverview } from '@/components/AgentOverview'
import { useSetDockPage } from '@/components/dock-context'
import { useAgentIngressFallbackBaseUrl, usePosthogBaseUrl, useSessionTeamId } from '@/components/session-context'
import { getAgentStats, listSessionsForAgent } from '@/lib/apiClient'
import { aiObservabilityTracesUrl } from '@/lib/posthogLinks'
import { useResource } from '@/lib/useResource'

export function OverviewSegment(): React.ReactElement {
    const agent = useAgent()
    const revisions = useRevisions()
    const teamId = useSessionTeamId()!
    const posthogBaseUrl = usePosthogBaseUrl()
    const router = useRouter()

    useSetDockPage({ kind: 'agent', agent: { id: agent.id, name: agent.name, slug: agent.slug } })

    // Stats + sessions: best-effort. Janitor 404 / 502 leaves the panel
    // with zeros + an empty list rather than failing the segment. Both
    // poll on a short interval — this is a live monitoring surface.
    const POLL_MS = 10_000
    const stats = useResource(() => getAgentStats(teamId, agent.slug).catch(() => null), [teamId, agent.slug], {
        pollMs: POLL_MS,
    })
    const sessions = useResource(
        () =>
            listSessionsForAgent(
                teamId,
                agent.slug,
                { id: agent.id, name: agent.name, slug: agent.slug },
                { limit: 5 }
            ).catch(() => ({ sessions: [], count: 0 })),
        [teamId, agent.slug, agent.id],
        { pollMs: POLL_MS }
    )

    const liveRevision = revisions.find((r) => r.id === agent.live_revision) ?? null
    const recentSessions = useMemo(() => (sessions.data?.sessions ?? []).slice(0, 5), [sessions.data])

    // Django's ingress_base_url is canonical; the console-config fallback
    // covers local dev where Django has no AGENT_INGRESS_PUBLIC_URL.
    const fallbackIngressBase = useAgentIngressFallbackBaseUrl(agent.slug)
    const ingressBaseUrl = agent.ingress_base_url ?? fallbackIngressBase

    const effectiveStats = stats.data ?? {
        liveCount: 0,
        sessions24hCount: 0,
        spend24hUsd: 0,
        lastActivityAt: undefined,
        failureRate24h: undefined,
    }

    return (
        <div className="mx-auto h-full max-w-5xl overflow-y-auto px-6 pb-6 pt-4">
            <AgentOverview
                agent={agent}
                liveRevision={liveRevision}
                stats={effectiveStats}
                recentSessions={recentSessions}
                aiObservabilityUrl={posthogBaseUrl ? aiObservabilityTracesUrl(posthogBaseUrl, teamId) : undefined}
                ingressBaseUrl={ingressBaseUrl}
                onOpenSession={(id) => router.push(`/agents/${agent.slug}/sessions?session=${encodeURIComponent(id)}`)}
                onOpenConfiguration={() => router.push(`/agents/${agent.slug}/configuration`)}
                onOpenTriggers={() =>
                    router.push(`/agents/${agent.slug}/configuration?node=${encodeURIComponent('cfg:triggers')}`)
                }
                onOpenSessions={() => router.push(`/agents/${agent.slug}/sessions`)}
            />
        </div>
    )
}
