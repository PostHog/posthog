/**
 * `<ApprovalDetail />` — embeddable detail panel for a single approval
 * request. Lives in the right pane of the approvals master-detail layout
 * (parent owns which row is selected via the `?request=` URL param).
 *
 * Two tabs: **Approval** (model reasoning, proposed args, decision
 * controls) and **Session** (the agent runtime session that proposed the
 * gated call, rendered with the shared `<SessionDetail>` so the approver
 * gets the full conversation + logs for context).
 *
 * Decision controls only render while the row is still `queued`. The form
 * disables submit while a request is in flight, surfaces server errors
 * inline, and on success calls `onDecided(state)` so the parent can
 * refetch the list. The panel stays open afterwards so the approver can
 * watch the decided outcome (state, dispatch result) land via polling.
 */

import { Loader2Icon, LockIcon, XIcon } from 'lucide-react'
import { useMemo, useState } from 'react'

import type { ChatSession } from '@posthog/agent-chat'
import type { LogEntry } from '@posthog/agent-chat/fixtures'
import {
    Badge,
    Button,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Textarea,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { usePosthogBaseUrl, useSessionTeamId } from '@/components/session-context'
import {
    ApiError,
    ApprovalRequest,
    decideApproval,
    DecideApprovalInput,
    getApproval,
    getSession,
    listLogsForSession,
} from '@/lib/apiClient'
import { aiObservabilityTraceUrl } from '@/lib/posthogLinks'
import { type ResourceState, useResource } from '@/lib/useResource'
import { SessionDetail } from '@/screens/SessionDetail'

/** Sessions + approvals change while an agent is running, so the detail polls. */
const POLL_MS = 10_000

type Agent = { id: string; name: string; slug: string }

export interface ApprovalDetailProps {
    /** Null renders nothing — the parent only mounts this when a row is selected. */
    approvalId: string | null
    /** The agent that owns this approval — used for the API URL and to hydrate its session. */
    agent: Agent | null
    /** Clears the host's `?request=` param. */
    onClose: () => void
    /** Fires after a successful approve / reject so the parent list can refetch. */
    onDecided?: (next: 'approving' | 'rejected') => void
}

export function ApprovalDetail({
    approvalId,
    agent,
    onClose,
    onDecided,
}: ApprovalDetailProps): React.ReactElement | null {
    if (!approvalId || !agent) {
        return null
    }
    return <DetailBody key={approvalId} approvalId={approvalId} agent={agent} onClose={onClose} onDecided={onDecided} />
}

interface DetailBodyProps {
    approvalId: string
    agent: Agent
    onClose: () => void
    onDecided?: (next: 'approving' | 'rejected') => void
}

function DetailBody({ approvalId, agent, onClose, onDecided }: DetailBodyProps): React.ReactElement {
    const teamId = useSessionTeamId()!

    const approvalRes = useResource(
        () => getApproval(teamId, agent.slug, approvalId),
        [teamId, agent.slug, approvalId],
        { pollMs: POLL_MS }
    )
    const approval = approvalRes.data
    const sessionId = approval?.session_id ?? null

    const sessionRes = useResource(
        () => (sessionId ? getSession(teamId, agent.slug, sessionId, agent).catch(() => null) : Promise.resolve(null)),
        [teamId, agent.slug, sessionId, agent.id],
        { pollMs: POLL_MS }
    )
    const logsRes = useResource(
        () => (sessionId ? listLogsForSession(teamId, agent.slug, sessionId).catch(() => []) : Promise.resolve([])),
        [teamId, agent.slug, sessionId],
        { pollMs: POLL_MS }
    )

    if (approvalRes.error) {
        const message =
            approvalRes.error instanceof ApiError && approvalRes.error.status === 404
                ? 'This approval no longer exists.'
                : approvalRes.error.message
        return (
            <PanelShell title="Approval request" onClose={onClose}>
                <div className="px-4 py-4 text-sm text-destructive-foreground">{message}</div>
            </PanelShell>
        )
    }

    if (!approval) {
        return (
            <PanelShell title="Loading approval…" onClose={onClose}>
                <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
                    <Loader2Icon className="h-4 w-4 animate-spin" />
                </div>
            </PanelShell>
        )
    }

    return (
        <Loaded
            approval={approval}
            agent={agent}
            sessionState={sessionRes}
            logs={logsRes.data ?? []}
            onClose={onClose}
            onDecided={onDecided}
            reloadApproval={approvalRes.reload}
        />
    )
}

/** Header chrome shared by the loading / error / loaded states. */
function PanelShell({
    title,
    subtitle,
    onClose,
    children,
}: {
    title: React.ReactNode
    subtitle?: React.ReactNode
    onClose: () => void
    children: React.ReactNode
}): React.ReactElement {
    return (
        <div className="flex h-full min-h-0 flex-col">
            <header className="flex shrink-0 items-start justify-between gap-3 border-b border-border px-4 py-3">
                <div className="min-w-0">
                    <div className="flex items-center gap-2 text-sm">{title}</div>
                    {subtitle ? <div className="mt-0.5 text-xs text-muted-foreground">{subtitle}</div> : null}
                </div>
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <button
                                type="button"
                                onClick={onClose}
                                aria-label="Close approval"
                                className="inline-flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
                            >
                                <XIcon className="h-4 w-4" />
                            </button>
                        }
                    />
                    <TooltipContent side="left">Close approval</TooltipContent>
                </Tooltip>
            </header>
            {children}
        </div>
    )
}

interface LoadedProps {
    approval: ApprovalRequest
    agent: Agent
    sessionState: ResourceState<ChatSession | null>
    logs: LogEntry[]
    onClose: () => void
    onDecided?: (next: 'approving' | 'rejected') => void
    reloadApproval: () => void
}

type Pane = 'approval' | 'session'

function Loaded({
    approval,
    agent,
    sessionState,
    logs,
    onClose,
    onDecided,
    reloadApproval,
}: LoadedProps): React.ReactElement {
    const teamId = useSessionTeamId()!
    const posthogBaseUrl = usePosthogBaseUrl()
    const scope = approval.approver_scope as ApproverScope
    const allowEdit = scope?.allow_edit === true
    const isQueued = approval.state === 'queued'

    const [pane, setPane] = useState<Pane>('approval')
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
            const res = await decideApproval(teamId, agent.slug, approval.id, body)
            onDecided?.(res.state)
            // Stay open and refetch so the approver sees the decided outcome land.
            reloadApproval()
        } catch (err) {
            setServerError(err instanceof Error ? err.message : String(err))
        } finally {
            setSubmitting(null)
        }
    }

    const sessionId = approval.session_id
    const obsUrl = posthogBaseUrl && sessionId ? aiObservabilityTraceUrl(posthogBaseUrl, teamId, sessionId) : undefined

    return (
        <div className="flex h-full min-h-0 flex-col">
            <header className="flex shrink-0 items-start justify-between gap-3 border-b border-border px-4 py-3">
                <div className="min-w-0">
                    <div className="flex items-center gap-2 text-sm">
                        <LockIcon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                        <code className="truncate font-mono text-sm font-medium text-foreground">
                            {approval.tool_name}
                        </code>
                        <StateBadge state={approval.state} />
                    </div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                        <span className="text-foreground">{agent.name}</span>
                        <span className="px-1.5 text-muted-foreground/60">·</span>
                        <span>{relativeAge(approval.created_at)} ago</span>
                        {isQueued ? (
                            <>
                                <span className="px-1.5 text-muted-foreground/60">·</span>
                                <span>expires {relativeDelta(approval.expires_at)}</span>
                            </>
                        ) : null}
                    </div>
                </div>
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <button
                                type="button"
                                onClick={onClose}
                                aria-label="Close approval"
                                className="inline-flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
                            >
                                <XIcon className="h-4 w-4" />
                            </button>
                        }
                    />
                    <TooltipContent side="left">Close approval</TooltipContent>
                </Tooltip>
            </header>

            <Tabs
                value={pane}
                onValueChange={(v) => setPane(v as Pane)}
                className="flex min-h-0 flex-1 flex-col gap-0 overflow-hidden"
            >
                <div className="flex shrink-0 items-center border-b border-border px-4">
                    <TabsList variant="line">
                        <TabsTrigger value="approval">Approval</TabsTrigger>
                        <TabsTrigger value="session">Session</TabsTrigger>
                    </TabsList>
                </div>

                <TabsContent value="approval" className="flex min-h-0 flex-1 flex-col overflow-hidden">
                    <div className="flex-1 space-y-6 overflow-y-auto px-4 py-4 text-sm">
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
                                            This tool's spec doesn't allow editing arguments — approval dispatches with
                                            the model's exact args.
                                        </p>
                                    )}

                                    <div className="space-y-1.5">
                                        <label
                                            className="text-xs font-medium text-foreground"
                                            htmlFor="approval-reason"
                                        >
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

                                    {serverError ? (
                                        <p className="text-xs text-destructive-foreground">{serverError}</p>
                                    ) : null}
                                </div>
                            </Section>
                        ) : null}
                    </div>

                    {isQueued ? (
                        <div className="flex shrink-0 justify-end gap-2 border-t border-border px-4 py-3">
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
                </TabsContent>

                <TabsContent value="session" className="min-h-0 flex-1 overflow-hidden">
                    {sessionState.data ? (
                        <SessionDetail session={sessionState.data} logs={logs} aiObservabilityTraceUrl={obsUrl} />
                    ) : sessionState.loading ? (
                        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                            <Loader2Icon className="h-4 w-4 animate-spin" />
                        </div>
                    ) : (
                        <div className="flex h-full items-center justify-center px-4 text-center text-sm text-muted-foreground">
                            Couldn't load the session that proposed this call.
                        </div>
                    )}
                </TabsContent>
            </Tabs>
        </div>
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
