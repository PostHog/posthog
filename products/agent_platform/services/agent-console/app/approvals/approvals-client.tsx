'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useMemo } from 'react'

import { useSetDockPage } from '@/components/dock-context'
import { useSessionTeamId } from '@/components/session-context'
import { ApiError, listAgents, listFleetApprovals } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'
import { Approvals } from '@/screens/Approvals'

const POLL_MS = 10_000

export function ApprovalsClient(): React.ReactElement {
    const teamId = useSessionTeamId()!
    const router = useRouter()
    const searchParams = useSearchParams()
    // Deep link from a gated tool call: `/approvals?request=<id>` opens that
    // approval's detail directly (the link the agent surfaces to the approver).
    const selectedId = searchParams?.get('request') ?? null

    useSetDockPage({ kind: 'agent-list' })

    const approvals = useResource(() => listFleetApprovals(teamId).catch(toApiError), [teamId], { pollMs: POLL_MS })
    const agents = useResource(() => listAgents(teamId).catch(() => []), [teamId])

    const select = useCallback(
        (id: string | null) => {
            const params = new URLSearchParams(searchParams?.toString() ?? '')
            if (id) {
                params.set('request', id)
            } else {
                params.delete('request')
            }
            const qs = params.toString()
            router.push(`/approvals${qs ? `?${qs}` : ''}`, { scroll: false })
        },
        [router, searchParams]
    )

    const errorMessage = useMemo(() => {
        const e = approvals.error
        if (!e) {
            return null
        }
        if (e instanceof ApiError && e.status === 404) {
            return "Approvals are admin-only — your account doesn't have admin scope on this project."
        }
        return e.message
    }, [approvals.error])

    return (
        <Approvals
            approvals={approvals.data ?? []}
            agents={agents.data ?? []}
            loading={approvals.loading}
            error={errorMessage}
            onReload={approvals.reload}
            selectedId={selectedId}
            onSelect={select}
        />
    )
}

/** Re-throw so `useResource` surfaces the structured error. */
function toApiError(err: unknown): never {
    throw err instanceof Error ? err : new Error(String(err))
}
