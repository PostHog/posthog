/**
 * `<AgentChat />` — the agent conversation surface.
 *
 * Renders one of:
 *  - Waiting (no turns yet) → contextual greeting + starter prompts.
 *  - Active (turns present) → conversation transcript.
 *  - Approval / error / disconnected → inline overlays on the transcript.
 *
 * Presentation-mode agnostic: this component fills its parent and
 * carries no chrome of its own (no rounded card, no max-width, no
 * fixed dock header). Hosts wrap it for their layout — a side rail,
 * a floating overlay, a fullscreen panel — and inject any chrome via
 * the `headerSlot` prop. The two surfaces today are the console's
 * embedded dock and storybook's standalone frames.
 *
 * v0 is fixture-driven — `session` is the source of truth; `onSend`
 * etc. are no-ops unless the host wires them. v0.2 replaces the
 * prop-driven session with an internal controller against ingress.
 */

import { ArrowUpIcon, SquareIcon, XIcon } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { ApprovalCard } from './components/ApprovalCard'
import type { ClientToolOutcome } from './components/parts'
import { TurnRow } from './components/Turn'
import { WaitingState } from './components/WaitingState'
import type { ChatContext, StarterPrompt } from './context'
import { getStarterPrompts } from './context'
import type { ChatSession, ClientToolHandler } from './types'

export interface AgentChatProps {
    context: ChatContext
    /** Fully-formed session to render. v0 only — v0.2 swaps for a controller. */
    session: ChatSession
    /** Override starter prompts; defaults derived from `context`. */
    starterPrompts?: StarterPrompt[]
    /**
     * Optional chrome rendered above the transcript. Used by hosts to
     * drop in a header (mode pill, exit-playground button, settings
     * menu, etc.). When unset, the transcript starts at the top of the
     * container — fine for stories and minimal embeds.
     */
    headerSlot?: React.ReactNode
    /**
     * Handlers for the `kind: "client"` tools this agent's spec declares.
     * Two shapes (see `ClientToolHandler`):
     *   - sync `handle` — invoked by the host's runner outside this
     *     component; the chat surface never calls it.
     *   - inline `render` — the chat surface renders the supplied UI
     *     next to the matching `tool_call` part while the call is
     *     unresolved. Use `onClientToolResolve` to wire submissions
     *     back to the runner.
     */
    handlers?: ClientToolHandler[]
    /**
     * Wired to the host's runner: when a render-style client tool's
     * inline UI submits, the chat calls this to post the result back.
     * In `useRealRunner` this is `runner.resolveClientTool`.
     */
    onClientToolResolve?: (callId: string, outcome: ClientToolOutcome) => void
    onSend?: (text: string) => void
    /**
     * Called when the user clicks Stop mid-stream. The host should
     * halt local streaming (close SSE, finalize the active turn)
     * without destroying the session — sending again should keep
     * the same conversation.
     */
    onStop?: () => void
    onApprove?: (callId: string) => void
    onDeny?: (callId: string) => void
    onReconnect?: () => void
    /**
     * Transport-level error from the underlying runner (e.g. a failed
     * `/run` request, ingress 5xx, lost SSE connection). Distinct from
     * `session.state === 'error'` which is a server-side terminal
     * outcome. The banner surfaces a friendly explanation + retry/dismiss
     * controls. Null/undefined → no banner.
     */
    transportError?: TransportError | null
    /** Called when the user dismisses the transport error banner. */
    onDismissTransportError?: () => void
    /**
     * Render assistant text as markdown when true. Off → plain
     * `whitespace-pre-wrap`. Hosts persist + toggle the preference and
     * pass it through; the chat lib itself only consumes the value.
     */
    renderMarkdown?: boolean
    /**
     * Optional host-provided summary renderer for tool-call cards.
     * Receives a resolved tool-call part and returns a node rendered
     * between the card header and the JSON drawer — used to surface
     * a clickable destination link for `focus_*` tools, styled error
     * reasons for failures, etc. Returning `null` (or omitting the
     * prop) falls back to the bare collapsed card.
     */
    renderToolSummary?: (part: Extract<import('./types').AssistantTurnPart, { kind: 'tool_call' }>) => React.ReactNode | null
}

/**
 * Shape callers produce from whatever transport layer they're using
 * (the console's `useRealRunner` builds this from `IngressError` /
 * EventSource error events). Keeping the agent-chat side decoupled
 * from any specific HTTP client.
 */
export interface TransportError {
    /** HTTP status when known; -1 for transport-level failures (DNS, network, EventSource drop). */
    status: number
    /** Stable code from the wire, e.g. `upstream_unreachable` / `no_chat_trigger` / `preview_token_required`. */
    code?: string
    /** Human-readable detail, falls back to a generic message based on status + code. */
    detail?: string
}

export function AgentChat({
    context,
    session,
    starterPrompts,
    headerSlot,
    handlers,
    onClientToolResolve,
    onSend,
    onStop,
    onApprove,
    onDeny,
    onReconnect,
    transportError,
    onDismissTransportError,
    renderMarkdown = true,
    renderToolSummary,
}: AgentChatProps): React.ReactElement {
    const [draft, setDraft] = useState('')
    const inputId = useId()
    const scrollRef = useRef<HTMLDivElement | null>(null)
    // Sticky-to-bottom: track whether the user is currently parked at
    // the bottom. While they are, we keep autoscrolling as the stream
    // grows; the moment they scroll up we stop following so they can
    // read history without getting yanked back.
    const stuckToBottomRef = useRef(true)

    // `streaming` is no longer disabling — the user can queue follow-ups
    // mid-turn; `/send` appends to `pending_inputs` server-side and the
    // runner drains them at the start of the next turn. The other live
    // states still need a focused decision before more input lands.
    const streaming = session.state === 'streaming'
    const awaitingClientTool = session.state === 'awaiting_client_tool'
    const sending = streaming || awaitingClientTool
    const inputDisabled = awaitingClientTool || session.state === 'awaiting_approval' || session.state === 'error'
    const waiting = session.turns.length === 0
    const effectivePrompts = starterPrompts ?? getStarterPrompts(context)
    const turnCount = session.turns.length

    useEffect(() => {
        const el = scrollRef.current
        if (!el) {
            return
        }
        const onScroll = (): void => {
            const distance = el.scrollHeight - el.scrollTop - el.clientHeight
            stuckToBottomRef.current = distance < 40
        }
        el.addEventListener('scroll', onScroll, { passive: true })
        return () => el.removeEventListener('scroll', onScroll)
    }, [])

    useEffect(() => {
        stuckToBottomRef.current = true
        const el = scrollRef.current
        if (el) {
            el.scrollTop = el.scrollHeight
        }
    }, [turnCount])

    useEffect(() => {
        if (!stuckToBottomRef.current) {
            return
        }
        const el = scrollRef.current
        if (!el) {
            return
        }
        el.scrollTop = el.scrollHeight
    })

    const send = (text: string): void => {
        const trimmed = text.trim()
        if (!trimmed) {
            return
        }
        onSend?.(trimmed)
        setDraft('')
    }

    return (
        <div
            className="flex h-full w-full flex-col"
            data-slot="agent-chat"
            data-mode={context.mode}
            data-state={session.state}
        >
            {headerSlot}

            <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
                {transportError ? (
                    <div className="px-4 pt-4">
                        <TransportErrorBanner error={transportError} onDismiss={onDismissTransportError} />
                    </div>
                ) : null}
                {waiting ? (
                    <WaitingState context={context} starterPrompts={effectivePrompts} onStart={send} />
                ) : (
                    <div className="space-y-3 px-4 py-4">
                        {session.turns.map((turn) => (
                            <TurnRow
                                key={turn.id}
                                turn={turn}
                                renderMarkdown={renderMarkdown}
                                handlers={handlers}
                                sessionId={session.id}
                                onClientToolResolve={onClientToolResolve}
                                renderToolSummary={renderToolSummary}
                            />
                        ))}
                        {session.pendingApprovals.map((a) => (
                            <ApprovalCard key={a.callId} approval={a} onApprove={onApprove} onDeny={onDeny} />
                        ))}
                        {session.state === 'disconnected' ? <DisconnectedBanner onReconnect={onReconnect} /> : null}
                        {session.state === 'error' && session.error ? <ErrorBanner message={session.error} /> : null}
                    </div>
                )}
            </div>

            <Footer
                draft={draft}
                inputId={inputId}
                disabled={inputDisabled}
                sending={sending}
                placeholder={placeholderFor(context, sending)}
                usage={session.usage}
                onChange={setDraft}
                onSubmit={() => send(draft)}
                onStop={onStop}
            />
        </div>
    )
}

function placeholderFor(context: ChatContext, sending: boolean): string {
    if (sending) {
        return context.mode === 'playground' ? `Queue a message for ${context.agent.name}` : 'Queue a message'
    }
    if (context.mode === 'playground') {
        return `Message ${context.agent.name}`
    }
    return 'Ask the concierge'
}

function DisconnectedBanner({ onReconnect }: { onReconnect?: () => void }): React.ReactElement {
    return (
        <div className="flex items-center gap-2 rounded-md border border-warning/40 bg-warning/5 px-3 py-2 text-xs text-warning-foreground">
            <span>Connection lost — your session is preserved.</span>
            <button
                type="button"
                className="ml-auto rounded-md border border-border/60 bg-background px-2 py-0.5 text-xs hover:bg-accent"
                onClick={() => onReconnect?.()}
            >
                Reconnect
            </button>
        </div>
    )
}

function ErrorBanner({ message }: { message: string }): React.ReactElement {
    return (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive-foreground">
            {message}
        </div>
    )
}

function describeTransportError(err: TransportError): { title: string; body: string } {
    const code = err.code ?? ''
    const detail = err.detail?.trim() || ''
    if (code === 'upstream_unreachable' || err.status === 502 || err.status === -1) {
        return {
            title: 'Agent platform unreachable',
            body: detail || 'Could not reach the agent runtime. Check that the ingress service is running, then try again.',
        }
    }
    if (code === 'no_chat_trigger') {
        return {
            title: 'No chat trigger on this revision',
            body: detail || 'This agent revision was not built to accept chat. Update its spec to add a `chat` trigger.',
        }
    }
    if (code === 'preview_token_required' || code === 'preview_token_expired') {
        return {
            title: 'Preview token expired',
            body: detail || 'The short-lived preview token has expired. Send your message again to mint a fresh one.',
        }
    }
    if (err.status === 401) {
        return {
            title: 'Sign-in expired',
            body: detail || 'Your session has timed out. Refresh the page to sign in again.',
        }
    }
    if (err.status === 404) {
        return {
            title: 'Agent not found',
            body: detail || 'The runtime returned 404 for this agent. It may have been archived or removed.',
        }
    }
    if (err.status === 410) {
        return {
            title: 'Session ended',
            body: detail || 'This session has been closed and can no longer receive messages.',
        }
    }
    return {
        title: err.status > 0 ? `Request failed (${err.status})` : 'Connection lost',
        body: detail || code || 'Try again in a moment.',
    }
}

function TransportErrorBanner({
    error,
    onDismiss,
}: {
    error: TransportError
    onDismiss?: () => void
}): React.ReactElement {
    const { title, body } = describeTransportError(error)
    return (
        <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-destructive-foreground/30 bg-destructive/40 px-3 py-2 text-xs"
        >
            <div className="min-w-0 flex-1 space-y-0.5">
                <p className="font-medium text-foreground">{title}</p>
                <p className="text-muted-foreground">{body}</p>
            </div>
            {onDismiss ? (
                <button
                    type="button"
                    onClick={onDismiss}
                    aria-label="Dismiss"
                    className="ml-2 inline-flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/30 hover:text-foreground"
                >
                    <XIcon className="h-3 w-3" />
                </button>
            ) : null}
        </div>
    )
}

function Footer({
    draft,
    inputId,
    disabled,
    sending,
    placeholder,
    usage,
    onChange,
    onSubmit,
    onStop,
}: {
    draft: string
    inputId: string
    disabled: boolean
    sending: boolean
    placeholder: string
    usage: ChatSession['usage']
    onChange: (next: string) => void
    onSubmit: () => void
    onStop?: () => void
}): React.ReactElement {
    const showStop = sending && onStop !== undefined
    const textareaRef = useRef<HTMLTextAreaElement>(null)
    // Auto-grow with the content up to a max — `rows={1}` alone leaves long
    // drafts clipped behind a fixed-height box. We reset to `auto` first so
    // shrinking on backspace works; the inline max-h cap matches the Tailwind
    // class so the visual matches the JS budget.
    useEffect(() => {
        const el = textareaRef.current
        if (!el) {
            return
        }
        el.style.height = 'auto'
        const MAX_PX = 192 // matches max-h-48 below
        el.style.height = Math.min(el.scrollHeight, MAX_PX) + 'px'
    }, [draft])
    return (
        <div className="border-t border-border">
            <form
                className="flex items-end gap-2 px-3 py-2.5"
                onSubmit={(e) => {
                    e.preventDefault()
                    onSubmit()
                }}
            >
                <label htmlFor={inputId} className="sr-only">
                    Send a message
                </label>
                <textarea
                    id={inputId}
                    ref={textareaRef}
                    rows={1}
                    className="max-h-48 min-h-[2rem] flex-1 resize-none overflow-y-auto rounded-md border border-input bg-background px-2 py-1.5 text-sm leading-snug placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50"
                    placeholder={placeholder}
                    value={draft}
                    onChange={(e) => onChange(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault()
                            onSubmit()
                            return
                        }
                        if (e.key === 'Escape' && showStop) {
                            e.preventDefault()
                            onStop?.()
                        }
                    }}
                    disabled={disabled}
                />
                {showStop ? (
                    <button
                        type="button"
                        aria-label="Stop generating"
                        title="Stop generating"
                        onClick={() => onStop?.()}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background text-foreground transition-colors hover:bg-accent"
                    >
                        <SquareIcon className="h-3 w-3 fill-current" />
                    </button>
                ) : null}
                <button
                    type="submit"
                    aria-label="Send"
                    disabled={disabled || draft.trim().length === 0}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                >
                    <ArrowUpIcon className="h-4 w-4" />
                </button>
            </form>
            <div className="flex items-center justify-between px-3 pb-1.5 text-[0.6875rem] text-muted-foreground">
                <span>
                    {sending
                        ? showStop
                            ? 'streaming · Enter to queue · Esc to stop'
                            : 'streaming · Enter to queue'
                        : 'Enter to send · Shift+Enter for newline'}
                </span>
                <span>${usage.costUsd.toFixed(3)}</span>
            </div>
        </div>
    )
}
