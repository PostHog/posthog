/**
 * `<ApprovalDetail />` — slide-out drawer rendering a single approval
 * request. Loaded lazily by id; parent owns open/close + which row is
 * selected.
 *
 * Decision controls only render when the row is still `queued`. The form
 * disables submit while a request is in flight, surfaces server errors
 * inline, and on success calls `onDecided(state)` so the parent can
 * optimistically remove the row from the list.
 */

import { Loader2Icon, LockIcon } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import {
    Badge,
    Button,
    Drawer,
    DrawerBackdrop,
    DrawerClose,
    DrawerContent,
    DrawerDescription,
    DrawerFooter,
    DrawerHeader,
    DrawerPortal,
    DrawerTitle,
    Textarea,
} from '@posthog/quill'

import { ApiError, ApprovalRequest, decideApproval, DecideApprovalInput, getApproval } from '@/lib/apiClient'

import { useSessionTeamId } from './session-context'

export interface ApprovalDetailProps {
    /** Closed when null; opens when set. */
    approvalId: string | null
    /** Used to build the API URL — every approval is scoped to one agent. */
    agentSlug: string | null
    /** Display name for the header. */
    agentName?: string | null
    onClose: () => void
    /**
     * Fires after a successful approve / reject so the parent list can
     * remove the row optimistically and refetch.
     */
    onDecided?: (next: 'approving' | 'rejected') => void
}

export function ApprovalDetail({
    approvalId,
    agentSlug,
    agentName,
    onClose,
    onDecided,
}: ApprovalDetailProps): React.ReactElement {
    return (
        <Drawer open={approvalId !== null} onOpenChange={(open) => !open && onClose()}>
            <DrawerPortal>
                <DrawerBackdrop />
                <DrawerContent className="!w-full !max-w-2xl">
                    {approvalId && agentSlug ? (
                        <DetailBody
                            key={approvalId}
                            approvalId={approvalId}
                            agentSlug={agentSlug}
                            agentName={agentName ?? null}
                            onClose={onClose}
                            onDecided={onDecided}
                        />
                    ) : null}
                </DrawerContent>
            </DrawerPortal>
        </Drawer>
    )
}

interface DetailBodyProps {
    approvalId: string
    agentSlug: string
    agentName: string | null
    onClose: () => void
    onDecided?: (next: 'approving' | 'rejected') => void
}

function DetailBody({ approvalId, agentSlug, agentName, onClose, onDecided }: DetailBodyProps): React.ReactElement {
    const teamId = useSessionTeamId()!
    const [approval, setApproval] = useState<ApprovalRequest | null>(null)
    const [loadError, setLoadError] = useState<string | null>(null)

    useEffect(() => {
        let cancelled = false
        setApproval(null)
        setLoadError(null)
        ;(async () => {
            try {
                const row = await getApproval(teamId, agentSlug, approvalId)
                if (!cancelled) {
                    setApproval(row)
                }
            } catch (err) {
                if (cancelled) {
                    return
                }
                setLoadError(
                    err instanceof ApiError && err.status === 404
                        ? 'This approval no longer exists.'
                        : err instanceof Error
                          ? err.message
                          : String(err)
                )
            }
        })()
        return () => {
            cancelled = true
        }
    }, [teamId, agentSlug, approvalId])

    if (loadError) {
        return (
            <>
                <DrawerHeader>
                    <DrawerTitle>Approval request</DrawerTitle>
                    <DrawerDescription>Couldn't load this approval.</DrawerDescription>
                </DrawerHeader>
                <div className="px-6 py-4 text-sm text-destructive-foreground">{loadError}</div>
                <DrawerFooter>
                    <DrawerClose render={<Button variant="outline" type="button" onClick={onClose} />}>
                        Close
                    </DrawerClose>
                </DrawerFooter>
            </>
        )
    }
    if (!approval) {
        return (
            <>
                <DrawerHeader>
                    <DrawerTitle>Loading approval…</DrawerTitle>
                </DrawerHeader>
                <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                    <Loader2Icon className="h-4 w-4 animate-spin" />
                </div>
            </>
        )
    }

    return (
        <Loaded
            approval={approval}
            agentSlug={agentSlug}
            agentName={agentName}
            onClose={onClose}
            onDecided={onDecided}
        />
    )
}

interface LoadedProps {
    approval: ApprovalRequest
    agentSlug: string
    agentName: string | null
    onClose: () => void
    onDecided?: (next: 'approving' | 'rejected') => void
}

function Loaded({ approval, agentSlug, agentName, onClose, onDecided }: LoadedProps): React.ReactElement {
    const teamId = useSessionTeamId()!
    const scope = approval.approver_scope as ApproverScope
    const allowEdit = scope?.allow_edit === true
    const isQueued = approval.state === 'queued'

    const [reason, setReason] = useState('')
    const [editMode, setEditMode] = useState(false)
    const [editedArgsText, setEditedArgsText] = useState<string>(() => JSON.stringify(approval.proposed_args, null, 2))
    const [argsParseError, setArgsParseError] = useState<string | null>(null)
    const [submitting, setSubmitting] = useState<null | 'approve' | 'reject'>(null)
    const [serverError, setServerError] = useState<string | null>(null)

    const submit = async (decision: 'approve' | 'reject'): Promise<void> => {
        if (submitting) {
            return
        }
        const body: DecideApprovalInput = { decision }
        if (reason.trim()) {
            body.reason = reason.trim()
        }
        if (decision === 'approve' && editMode && allowEdit) {
            try {
                body.edited_args = JSON.parse(editedArgsText) as Record<string, unknown>
            } catch (e) {
                setArgsParseError(e instanceof Error ? e.message : 'Invalid JSON')
                return
            }
        }
        setSubmitting(decision)
        setServerError(null)
        try {
            const res = await decideApproval(teamId, agentSlug, approval.id, body)
            onDecided?.(res.state)
            onClose()
        } catch (err) {
            setServerError(err instanceof Error ? err.message : String(err))
        } finally {
            setSubmitting(null)
        }
    }

    return (
        <>
            <DrawerHeader>
                <DrawerTitle className="flex items-center gap-2">
                    <LockIcon className="h-4 w-4 text-muted-foreground" aria-hidden />
                    <code className="font-mono text-sm">{approval.tool_name}</code>
                    <StateBadge state={approval.state} />
                </DrawerTitle>
                <DrawerDescription>
                    {agentName ? <span className="text-foreground">{agentName}</span> : null}
                    {agentName ? <span className="px-1.5 text-muted-foreground/60">·</span> : null}
                    <span>{relativeAge(approval.created_at)} ago</span>
                    {isQueued ? (
                        <>
                            <span className="px-1.5 text-muted-foreground/60">·</span>
                            <span>expires {relativeDelta(approval.expires_at)}</span>
                        </>
                    ) : null}
                </DrawerDescription>
            </DrawerHeader>

            <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6 text-sm">
                <AssistantSnapshot message={approval.assistant_message} />

                <Section title="Proposed arguments" hint="Frozen at intercept time.">
                    <JsonView value={approval.proposed_args} />
                </Section>

                {!isQueued ? <DecidedFooter approval={approval} /> : null}

                {isQueued ? (
                    <Section title="Decision">
                        <div className="space-y-3">
                            {allowEdit ? (
                                <div className="rounded-md border border-border bg-muted/20 p-3">
                                    <label className="flex items-center gap-2 text-xs font-medium text-foreground">
                                        <input
                                            type="checkbox"
                                            checked={editMode}
                                            onChange={(e) => {
                                                setEditMode(e.currentTarget.checked)
                                                setArgsParseError(null)
                                            }}
                                            disabled={submitting !== null}
                                        />
                                        Approve with edits
                                    </label>
                                    {editMode ? (
                                        <div className="mt-2 space-y-1.5">
                                            <Textarea
                                                value={editedArgsText}
                                                onChange={(e) => {
                                                    setEditedArgsText(e.currentTarget.value)
                                                    setArgsParseError(null)
                                                }}
                                                rows={8}
                                                spellCheck={false}
                                                className="font-mono text-[0.75rem]"
                                                disabled={submitting !== null}
                                            />
                                            <div className="flex items-center justify-between">
                                                <Button
                                                    type="button"
                                                    variant="link-muted"
                                                    size="sm"
                                                    disabled={submitting !== null}
                                                    onClick={() => {
                                                        setEditedArgsText(
                                                            JSON.stringify(approval.proposed_args, null, 2)
                                                        )
                                                        setArgsParseError(null)
                                                    }}
                                                >
                                                    Reset to proposed
                                                </Button>
                                                {argsParseError ? (
                                                    <span className="text-[0.6875rem] text-destructive-foreground">
                                                        {argsParseError}
                                                    </span>
                                                ) : null}
                                            </div>
                                        </div>
                                    ) : null}
                                </div>
                            ) : (
                                <p className="text-[0.6875rem] text-muted-foreground">
                                    This tool's spec doesn't allow editing arguments — approval dispatches with the
                                    model's exact args.
                                </p>
                            )}

                            <div className="space-y-1.5">
                                <label className="text-xs font-medium text-foreground" htmlFor="approval-reason">
                                    Reason (optional)
                                </label>
                                <Textarea
                                    id="approval-reason"
                                    value={reason}
                                    onChange={(e) => setReason(e.currentTarget.value)}
                                    rows={2}
                                    disabled={submitting !== null}
                                    placeholder="Why are you approving / rejecting?"
                                />
                            </div>

                            {serverError ? <p className="text-xs text-destructive-foreground">{serverError}</p> : null}
                        </div>
                    </Section>
                ) : null}
            </div>

            <DrawerFooter className="flex-row justify-between">
                <DrawerClose render={<Button variant="outline" type="button" disabled={submitting !== null} />}>
                    Close
                </DrawerClose>
                {isQueued ? (
                    <div className="flex gap-2">
                        <Button
                            type="button"
                            variant="outline"
                            onClick={() => submit('reject')}
                            disabled={submitting !== null}
                            aria-busy={submitting === 'reject' ? 'true' : undefined}
                        >
                            {submitting === 'reject' ? 'Rejecting…' : 'Reject'}
                        </Button>
                        <Button
                            type="button"
                            onClick={() => submit('approve')}
                            disabled={submitting !== null}
                            aria-busy={submitting === 'approve' ? 'true' : undefined}
                        >
                            {submitting === 'approve' ? 'Approving…' : editMode ? 'Approve with edits' : 'Approve'}
                        </Button>
                    </div>
                ) : null}
            </DrawerFooter>
        </>
    )
}

interface ApproverScope {
    approvers?: string[]
    allow_edit?: boolean
    allow_agent_approver?: boolean
}

function StateBadge({ state }: { state: ApprovalRequest['state'] }): React.ReactElement {
    type Variant = 'warning' | 'info' | 'success' | 'destructive' | 'default'
    const tone: Variant = (() => {
        switch (state) {
            case 'queued':
                return 'warning'
            case 'approving':
                return 'info'
            case 'dispatched':
                return 'success'
            case 'dispatched_failed':
                return 'destructive'
            case 'rejected':
            case 'expired':
            default:
                return 'default'
        }
    })()
    const label = state === 'dispatched_failed' ? 'dispatch failed' : state
    return <Badge variant={tone}>{label}</Badge>
}

function AssistantSnapshot({ message }: { message: Record<string, unknown> }): React.ReactElement | null {
    const parts = useMemo(() => extractAssistantParts(message), [message])
    if (parts.length === 0) {
        return null
    }
    return (
        <Section title="Model reasoning" hint="What the agent was thinking when it proposed this call.">
            <div className="space-y-2">
                {parts.map((p, i) =>
                    p.kind === 'thinking' ? (
                        <pre
                            key={i}
                            className="whitespace-pre-wrap rounded-md border border-dashed border-border bg-muted/20 px-3 py-2 text-xs italic text-muted-foreground"
                        >
                            {p.text}
                        </pre>
                    ) : (
                        <p key={i} className="whitespace-pre-wrap text-sm text-foreground">
                            {p.text}
                        </p>
                    )
                )}
            </div>
        </Section>
    )
}

function DecidedFooter({ approval }: { approval: ApprovalRequest }): React.ReactElement {
    return (
        <div className="space-y-3">
            <Section title="Decision">
                <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs">
                    <dt className="text-muted-foreground">By</dt>
                    <dd className="font-mono text-[0.75rem] text-foreground">
                        {approval.decision_by ?? <span className="text-muted-foreground/60">—</span>}
                    </dd>
                    <dt className="text-muted-foreground">When</dt>
                    <dd className="text-foreground">
                        {approval.decision_at ? new Date(approval.decision_at).toLocaleString() : '—'}
                    </dd>
                    <dt className="text-muted-foreground">Reason</dt>
                    <dd className="text-foreground">
                        {approval.decision_reason ?? <span className="text-muted-foreground/60">—</span>}
                    </dd>
                </dl>
            </Section>
            {approval.decided_args ? (
                <Section title="Approver-edited arguments" hint="What the tool actually ran with.">
                    <JsonView value={approval.decided_args as Record<string, unknown>} />
                </Section>
            ) : null}
            {approval.dispatch_outcome ? (
                <Section title="Dispatch outcome">
                    <DispatchOutcomeView outcome={approval.dispatch_outcome} />
                </Section>
            ) : null}
        </div>
    )
}

function DispatchOutcomeView({ outcome }: { outcome: Record<string, unknown> }): React.ReactElement {
    const error = typeof outcome.error === 'string' ? outcome.error : null
    if (error) {
        return (
            <pre className="whitespace-pre-wrap rounded-md border border-destructive-foreground/30 bg-destructive/10 px-3 py-2 text-xs text-destructive-foreground">
                {error}
            </pre>
        )
    }
    return <JsonView value={(outcome.result ?? outcome) as Record<string, unknown>} />
}

function Section({
    title,
    hint,
    children,
}: {
    title: string
    hint?: string
    children: React.ReactNode
}): React.ReactElement {
    return (
        <section className="space-y-2">
            <header>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
                {hint ? <p className="text-[0.6875rem] text-muted-foreground/80">{hint}</p> : null}
            </header>
            {children}
        </section>
    )
}

function JsonView({ value }: { value: unknown }): React.ReactElement {
    return (
        <pre className="max-h-72 overflow-auto rounded-md border border-border bg-muted/20 px-3 py-2 font-mono text-[0.75rem] text-foreground">
            {JSON.stringify(value, null, 2)}
        </pre>
    )
}

function extractAssistantParts(message: Record<string, unknown>): Array<{ kind: 'text' | 'thinking'; text: string }> {
    const out: Array<{ kind: 'text' | 'thinking'; text: string }> = []
    // Pi-ai-style { role: 'assistant', content: [{type, text/thinking}] }
    const content = message?.content
    if (Array.isArray(content)) {
        for (const part of content) {
            if (!part || typeof part !== 'object') {
                continue
            }
            const p = part as { type?: string; text?: string; thinking?: string }
            if (typeof p.text === 'string' && p.text.length > 0) {
                out.push({ kind: 'text', text: p.text })
            } else if (typeof p.thinking === 'string' && p.thinking.length > 0) {
                out.push({ kind: 'thinking', text: p.thinking })
            }
        }
    } else if (typeof content === 'string' && content.length > 0) {
        out.push({ kind: 'text', text: content })
    }
    return out
}

function relativeAge(iso: string): string {
    return humanizeMs(Date.now() - new Date(iso).getTime())
}

function relativeDelta(iso: string): string {
    const ms = new Date(iso).getTime() - Date.now()
    if (ms < 0) {
        return `${humanizeMs(-ms)} ago`
    }
    return `in ${humanizeMs(ms)}`
}

function humanizeMs(ms: number): string {
    if (!Number.isFinite(ms) || ms < 0) {
        return ''
    }
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
