'use client'

import { useAgent } from '@/components/agent-context'
import { useSetDockPage } from '@/components/dock-context'
import { FleetAnalytics } from '@/components/FleetAnalytics'
import { usePosthogBaseUrl, useSessionTeamId } from '@/components/session-context'
import { EMPTY_ANALYTICS, loadFleetAnalytics } from '@/lib/fleetAnalytics'
import { aiObservabilityTracesUrl } from '@/lib/posthogLinks'
import { useResource } from '@/lib/useResource'

export function ObservabilitySegment(): React.ReactElement {
    const agent = useAgent()
    const teamId = useSessionTeamId()!
    const posthogBaseUrl = usePosthogBaseUrl()

    useSetDockPage({ kind: 'agent', agent: { id: agent.id, name: agent.name, slug: agent.slug } })

    // Same rollups as the fleet board, scoped to this agent's application id.
    const analytics = useResource(() => loadFleetAnalytics(teamId, agent.id), [teamId, agent.id], { pollMs: 30_000 })

    return (
        <div className="h-full overflow-y-auto">
            <FleetAnalytics
                data={analytics.data ?? EMPTY_ANALYTICS}
                scope="agent"
                title="Observability"
                subtitle={`${agent.name} · last 7 days (14-day trend)`}
                aiObservabilityUrl={posthogBaseUrl ? aiObservabilityTracesUrl(posthogBaseUrl, teamId) : undefined}
                loading={analytics.loading && !analytics.data}
                error={!analytics.loading && !analytics.data ? (analytics.error?.message ?? 'Failed to load') : null}
            />
        </div>
    )
}
