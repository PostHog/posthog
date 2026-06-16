/**
 * `<ApprovalsList />` — the table behind both `/approvals` (fleet) and
 * `/agents/[slug]/approvals` (per-agent).
 *
 * Renders a flat list of `agent_tool_approval_request` rows with a state
 * filter strip + (in fleet mode) an agent filter chip. Each row links into
 * the detail drawer the parent screen owns. Polls via `useResource` on
 * the screen side; this component is pure presentation.
 */

import { ChevronRightIcon, LockIcon } from 'lucide-react'
import { useMemo, useState } from 'react'

import type { ApprovalRequest, ApprovalState } from '@/lib/apiClient'

import { FilterChips } from './FilterChips'

const FILTERS = ['queued', 'approving', 'decided', 'all'] as const
type Filter = (typeof FILTERS)[number]

export type AgentLookup = ReadonlyMap<string, { id: string; name: string; slug: string }>

export interface ApprovalsListProps {
    approvals: ApprovalRequest[]
    /**
     * Optional lookup so fleet-mode rows can resolve `application_id` to
     * the agent's display name + slug. Per-agent mode passes a 1-entry
     * map for the current agent.
     */
    agentsById?: AgentLookup
    /** Show the agent name column. Defaults to true in fleet mode (lookup > 1). */
    showAgentColumn?: boolean
    /** Highlights the matching row — drives the drawer open state. */
    selectedApprovalId?: string | null
    onOpenApproval?: (approvalId: string) => void
}

const DECIDED_STATES: ReadonlySet<ApprovalState> = new Set(['dispatched', 'dispatched_failed', 'rejected', 'expired'])

export function ApprovalsList({
    approvals,
    agentsById,
    showAgentColumn,
    selectedApprovalId,
    onOpenApproval,
}: ApprovalsListProps): React.ReactElement {
    const [filter, setFilter] = useState<Filter>('queued')

    const filtered = useMemo(() => {
        switch (filter) {
            case 'queued':
                return approvals.filter((a) => a.state === 'queued')
            case 'approving':
                return approvals.filter((a) => a.state === 'approving')
            case 'decided':
                return approvals.filter((a) => DECIDED_STATES.has(a.state))
            case 'all':
            default:
                return approvals
        }
    }, [approvals, filter])

    const includeAgentColumn = showAgentColumn ?? (agentsById ? agentsById.size > 1 : false)

    if (approvals.length === 0) {
        return (
            <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                No approval requests yet. Tool calls marked{' '}
                <code className="rounded bg-muted/40 px-1 py-0.5 text-[0.6875rem]">requires_approval</code> show up here
                when an agent proposes them.
            </div>
        )
    }

    return (
        <div className="space-y-3">
            <div className="flex items-center justify-between">
                <FilterChips
                    options={FILTERS}
                    value={filter}
                    onChange={setFilter}
                    labels={{ queued: 'Queued', approving: 'Approving', decided: 'Decided', all: 'All' }}
                />
                <span className="text-[0.6875rem] text-muted-foreground">
                    {filtered.length} of {approvals.length}
                </span>
            </div>

            {filtered.length === 0 ? (
                <div className="rounded-md border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
                    No approval requests match this filter.
                </div>
            ) : (
                <ul className="divide-y divide-border rounded-md border border-border bg-card">
                    {filtered.map((a) => (
                        <li key={a.id}>
                            <ApprovalRow
                                approval={a}
                                agent={agentsById?.get(a.application_id) ?? null}
                                showAgent={includeAgentColumn}
                                active={a.id === selectedApprovalId}
                                onOpen={onOpenApproval}
                            />
                        </li>
                    ))}
                </ul>
            )}
        </div>
    )
}

interface ApprovalRowProps {
    approval: ApprovalRequest
    agent: { id: string; name: string; slug: string } | null
    showAgent: boolean
    active: boolean
    onOpen?: (id: string) => void
}

function ApprovalRow({ approval, agent, showAgent, active, onOpen }: ApprovalRowProps): React.ReactElement {
    const tone = stateTone(approval.state)
    const argsPreview = previewArgs(approval.proposed_args)
    return (
        <button
            type="button"
            onClick={() => onOpen?.(approval.id)}
            className={
                'group flex w-full items-start gap-3 px-3 py-2.5 text-left transition-colors hover:bg-muted/40 ' +
                (active ? 'bg-muted/40' : '')
            }
        >
            <span className={`mt-1.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full ${tone.dotClass}`} aria-hidden />
            <div className="min-w-0 flex-1 space-y-0.5">
                <div className="flex items-center gap-2 text-xs">
                    <LockIcon className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden />
                    <code className="truncate font-mono text-[0.75rem] font-medium text-foreground">
                        {approval.tool_name}
                    </code>
                    {showAgent && agent ? (
                        <>
                            <span className="text-muted-foreground/60" aria-hidden>
                                ·
                            </span>
                            <span className="truncate text-muted-foreground">{agent.name}</span>
                        </>
                    ) : null}
                </div>
                <div className="flex items-center gap-2 text-[0.6875rem] text-muted-foreground">
                    <span>{tone.label}</span>
                    <span aria-hidden>·</span>
                    <span>{formatAge(approval.created_at)}</span>
                    {approval.state === 'queued' ? (
                        <>
                            <span aria-hidden>·</span>
                            <span>expires {formatRelative(approval.expires_at)}</span>
                        </>
                    ) : null}
                </div>
                {argsPreview ? (
                    <div className="truncate font-mono text-[0.6875rem] text-muted-foreground/80">{argsPreview}</div>
                ) : null}
            </div>
            <ChevronRightIcon className="mt-1 h-3.5 w-3.5 shrink-0 text-muted-foreground/60 transition-all group-hover:translate-x-0.5 group-hover:text-foreground" />
        </button>
    )
}

function stateTone(state: ApprovalState): { dotClass: string; label: string } {
    switch (state) {
        case 'queued':
            return { dotClass: 'bg-warning-foreground animate-pulse', label: 'queued' }
        case 'approving':
            return { dotClass: 'bg-info-foreground animate-pulse', label: 'approving' }
        case 'dispatched':
            return { dotClass: 'bg-success-foreground', label: 'dispatched' }
        case 'dispatched_failed':
            return { dotClass: 'bg-destructive-foreground', label: 'dispatch failed' }
        case 'rejected':
            return { dotClass: 'bg-muted-foreground/60', label: 'rejected' }
        case 'expired':
            return { dotClass: 'bg-muted-foreground/60', label: 'expired' }
        default:
            return { dotClass: 'bg-muted-foreground/60', label: state }
    }
}

function previewArgs(args: Record<string, unknown>): string {
    try {
        const s = JSON.stringify(args)
        if (s.length <= 90) {
            return s
        }
        return `${s.slice(0, 87)}…`
    } catch {
        return ''
    }
}

function formatAge(iso: string): string {
    const ageMs = Date.now() - new Date(iso).getTime()
    if (Number.isNaN(ageMs) || ageMs < 0) {
        return ''
    }
    return `${humanizeMs(ageMs)} ago`
}

function formatRelative(iso: string): string {
    const deltaMs = new Date(iso).getTime() - Date.now()
    if (Number.isNaN(deltaMs)) {
        return ''
    }
    if (deltaMs < 0) {
        return `${humanizeMs(-deltaMs)} ago`
    }
    return `in ${humanizeMs(deltaMs)}`
}

function humanizeMs(ms: number): string {
    const s = Math.round(ms / 1000)
    if (s < 60) {
        return `${s}s`
    }
    const m = Math.round(s / 60)
    if (m < 60) {
        return `${m}m`
    }
    const h = Math.round(m / 60)
    if (h < 48) {
        return `${h}h`
    }
    return `${Math.round(h / 24)}d`
}
