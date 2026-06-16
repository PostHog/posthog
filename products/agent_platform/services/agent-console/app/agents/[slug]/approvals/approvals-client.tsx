'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useMemo } from 'react'

import { useAgent } from '@/components/agent-context'
import { ApprovalDetail } from '@/components/ApprovalDetail'
import { type AgentLookup, ApprovalsList } from '@/components/ApprovalsList'
import { useSetDockPage } from '@/components/dock-context'
import { useSessionTeamId } from '@/components/session-context'
import { ApiError, listAgentApprovals } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'

const POLL_MS = 10_000

export function ApprovalsSegment(): React.ReactElement {
    const agent = useAgent()
    const teamId = useSessionTeamId()!
    const router = useRouter()
    const searchParams = useSearchParams()
    const selectedId = searchParams?.get('request') ?? null

    useSetDockPage({ kind: 'agent', agent: { id: agent.id, name: agent.name, slug: agent.slug } })

    const approvals = useResource(() => listAgentApprovals(teamId, agent.slug), [teamId, agent.slug], {
        pollMs: POLL_MS,
    })

    const select = useCallback(
        (id: string | null) => {
            const params = new URLSearchParams(searchParams?.toString() ?? '')
            if (id) {
                params.set('request', id)
            } else {
                params.delete('request')
            }
            const qs = params.toString()
            router.push(`/agents/${agent.slug}/approvals${qs ? `?${qs}` : ''}`, { scroll: false })
        },
        [agent.slug, router, searchParams]
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

    const agentsById = useMemo<AgentLookup>(
        () => new Map([[agent.id, { id: agent.id, name: agent.name, slug: agent.slug }]]),
        [agent.id, agent.name, agent.slug]
    )

    const rows = approvals.data ?? []
    const errorBanner = errorMessage ? (
        <div className="shrink-0 rounded-md border border-destructive-foreground/30 bg-destructive/10 px-3 py-2 text-xs text-destructive-foreground">
            {errorMessage}
        </div>
    ) : null

    const list = (
        <ApprovalsList
            approvals={rows}
            agentsById={agentsById}
            showAgentColumn={false}
            selectedApprovalId={selectedId}
            onOpenApproval={select}
        />
    )

    // Nothing selected → list takes the whole centered column.
    if (!selectedId) {
        return (
            <div className="mx-auto flex h-full w-full max-w-5xl flex-col gap-4 px-6 pb-6 pt-4">
                {errorBanner}
                {approvals.loading && rows.length === 0 ? (
                    <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                        Loading approvals…
                    </div>
                ) : (
                    list
                )}
            </div>
        )
    }

    return (
        <div className="grid h-full grid-cols-[minmax(280px,360px)_minmax(0,1fr)] divide-x divide-border">
            <aside className="flex min-h-0 flex-col overflow-y-auto px-3 py-3">
                {errorBanner}
                {list}
            </aside>
            <main className="min-h-0 overflow-hidden">
                <ApprovalDetail
                    approvalId={selectedId}
                    agent={{ id: agent.id, name: agent.name, slug: agent.slug }}
                    onClose={() => select(null)}
                    onDecided={() => approvals.reload()}
                />
            </main>
        </div>
    )
}
