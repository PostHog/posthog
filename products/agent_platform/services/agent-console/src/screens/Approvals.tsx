/**
 * `<Approvals />` — fleet-wide approval inbox.
 *
 * Pure presentation: receives the list + agent lookup + selection from the
 * route client (which owns the `?request=<id>` URL param). With nothing
 * selected the list takes the full centered column; selecting a row splits
 * into a master-detail grid (list on the left, `<ApprovalDetail>` on the
 * right) mirroring the sessions tab.
 */

import { useMemo } from 'react'

import type { AgentApplicationFixture } from '@posthog/agent-chat/fixtures'

import { ApprovalDetail } from '@/components/ApprovalDetail'
import { type AgentLookup, ApprovalsList } from '@/components/ApprovalsList'
import type { ApprovalRequest } from '@/lib/apiClient'

export interface ApprovalsProps {
    approvals: ApprovalRequest[]
    agents: AgentApplicationFixture[]
    /** `true` while the first fetch is in flight — skeleton placeholder. */
    loading: boolean
    /** Surface auth / server failures. */
    error: string | null
    /** Caller refetches the list after a successful decision. */
    onReload: () => void
    /** Selected approval id, driven by the `?request=<id>` URL param. */
    selectedId: string | null
    /** Push / clear the `?request=<id>` URL param. */
    onSelect: (id: string | null) => void
}

export function Approvals({
    approvals,
    agents,
    loading,
    error,
    onReload,
    selectedId,
    onSelect,
}: ApprovalsProps): React.ReactElement {
    const agentsById = useMemo<AgentLookup>(() => {
        const m = new Map<string, { id: string; name: string; slug: string }>()
        for (const a of agents) {
            m.set(a.id, { id: a.id, name: a.name, slug: a.slug })
        }
        return m
    }, [agents])

    const selected = useMemo(
        () => (selectedId ? (approvals.find((a) => a.id === selectedId) ?? null) : null),
        [approvals, selectedId]
    )
    const selectedAgent = selected ? (agentsById.get(selected.application_id) ?? null) : null

    const header = (
        <header className="flex shrink-0 items-end justify-between">
            <div>
                <h1 className="text-xl font-medium tracking-tight">Approvals</h1>
                <p className="text-sm text-muted-foreground">
                    Approval-gated tool calls across every agent in this project. Admin only.
                </p>
            </div>
        </header>
    )

    const errorBanner = error ? (
        <div className="shrink-0 rounded-md border border-destructive-foreground/30 bg-destructive/10 px-3 py-2 text-xs text-destructive-foreground">
            {error}
        </div>
    ) : null

    const list = (
        <ApprovalsList
            approvals={approvals}
            agentsById={agentsById}
            showAgentColumn
            selectedApprovalId={selectedId}
            onOpenApproval={onSelect}
        />
    )

    // Nothing selected → list takes the whole centered column.
    if (!selectedId) {
        return (
            <div className="mx-auto flex h-full w-full max-w-5xl flex-col gap-4 px-6 py-6">
                {header}
                {errorBanner}
                {loading && approvals.length === 0 ? (
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
        <div className="flex h-full w-full flex-col gap-4 px-6 py-6">
            {header}
            {errorBanner}
            <div className="grid min-h-0 flex-1 grid-cols-[minmax(280px,360px)_minmax(0,1fr)] divide-x divide-border overflow-hidden rounded-md border border-border">
                <aside className="flex min-h-0 flex-col overflow-y-auto px-3 py-3">{list}</aside>
                <main className="min-h-0 overflow-hidden">
                    <ApprovalDetail
                        approvalId={selectedId}
                        agent={selectedAgent}
                        onClose={() => onSelect(null)}
                        onDecided={onReload}
                    />
                </main>
            </div>
        </div>
    )
}
