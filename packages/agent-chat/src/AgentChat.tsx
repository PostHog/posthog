/**
 * `<AgentChat />` — the ambient chat dock.
 *
 * Lives pinned in the app shell. Renders one of three views:
 *  - Waiting (no turns yet) → contextual greeting + starter prompts.
 *  - Active (turns present) → conversation transcript.
 *  - Approval / error / disconnected — overlays on top of the transcript.
 *
 * Two modes:
 *  - `concierge` — the management AI; what it shows depends on the
 *    page the user is on (passed via `context.page`).
 *  - `playground` — explicit, talking *to* an agent. Visually flagged
 *    in the header; sticky across navigation.
 *
 * v0 is mocked — `session` is fixture data; `onSend` etc. are no-ops
 * unless the parent wires them. v0.2 replaces the prop-driven session
 * with an internal controller against the real ingress.
 */

import { ArrowUpIcon, XIcon } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { ApprovalCard } from './components/ApprovalCard'
import { DockHeader } from './components/DockHeader'
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
     * Handlers for the `kind: "client"` tools this agent's spec declares.
     * v0 doesn't invoke them at render time (results are baked into the
     * fixture); accepted so the API shape is stable across v0 → v0.2.
     */
    handlers?: ClientToolHandler[]
    /** Current focus-mode state — when off, the dock header narrates instead of navigating. */
    followingEnabled?: boolean
    /** Notified when the user toggles focus mode from the dock header. */
    onFollowingChange?: (next: boolean) => void
    onSend?: (text: string) => void
    onApprove?: (callId: string) => void
    onDeny?: (callId: string) => void
    onReconnect?: () => void
    onExitPlayground?: () => void
    /** Concierge-mode reset — clear the chat back to waiting state. */
    onNewSession?: () => void
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
     * Non-zero when the SSE listen stream is reconnecting after a
     * transient drop. The dock surfaces a quiet "Reconnecting…" pill
     * so the user knows the gap before the next event is recovery, not
     * a stall. Reset to 0 once a fresh event arrives.
     */
    reconnectAttempt?: number
    /**
     * Render assistant text as markdown when true. Off → plain
     * `whitespace-pre-wrap`. Persisted + toggled by the host (the
     * settings dropdown in the dock header writes through).
     */
    renderMarkdown?: boolean
    /** Notified when the user toggles the markdown setting in the dock header. */
    onRenderMarkdownChange?: (next: boolean) => void
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
    followingEnabled,
    onFollowingChange,
    onSend,
    onApprove,
    onDeny,
    onReconnect,
    onExitPlayground,
    onNewSession,
    transportError,
    onDismissTransportError,
    reconnectAttempt,
    renderMarkdown = true,
    onRenderMarkdownChange,
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

    // Wire a scroll listener once — it updates the sticky-to-bottom
    // flag based on the user's actual viewport position. 40px tolerance
    // so scrollbar twitch / a stray wheel tick doesn't drop us off the
    // tail.
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

    // A new turn (user message, assistant turn boundary) forces a
    // re-stick — sending your own message always pulls you back to the
    // bottom regardless of where you'd scrolled to.
    useEffect(() => {
        stuckToBottomRef.current = true
        const el = scrollRef.current
        if (el) {
            el.scrollTop = el.scrollHeight
        }
    }, [turnCount])

    // Follow streaming content: every render, if the user hasn't
    // scrolled away, keep them pinned to the bottom. Cheap — runs on
    // every assistant_text_delta but only mutates scrollTop if needed.
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
            className="flex h-full w-full flex-col bg-background"
            data-slot="agent-chat"
            data-mode={context.mode}
            data-state={session.state}
        >
            <DockHeader
                context={context}
                followingEnabled={followingEnabled}
                onFollowingChange={onFollowingChange}
                onExitPlayground={onExitPlayground}
                onNewSession={onNewSession}
                busy={sending}
                reconnectAttempt={reconnectAttempt}
                renderMarkdown={renderMarkdown}
                onRenderMarkdownChange={onRenderMarkdownChange}
            />

            <div ref={scrollRef} className="flex-1 overflow-y-auto">
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
                            <TurnRow key={turn.id} turn={turn} renderMarkdown={renderMarkdown} />
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

/**
 * Maps a known wire-level error to friendly title + body. Falls back
 * to the raw `detail` (or a generic line) so callers don't need to
 * pre-stringify anything.
 */
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
}: {
    draft: string
    inputId: string
    disabled: boolean
    sending: boolean
    placeholder: string
    usage: ChatSession['usage']
    onChange: (next: string) => void
    onSubmit: () => void
}): React.ReactElement {
    return (
        <div className="border-t border-border bg-background">
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
                    rows={1}
                    className="min-h-[2rem] flex-1 resize-none rounded-md border border-input bg-background px-2 py-1.5 text-sm leading-snug placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50"
                    placeholder={placeholder}
                    value={draft}
                    onChange={(e) => onChange(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault()
                            onSubmit()
                        }
                    }}
                    disabled={disabled}
                />
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
                <span>{sending ? 'streaming · Enter to queue' : 'Enter to send · Shift+Enter for newline'}</span>
                <span>${usage.costUsd.toFixed(3)}</span>
            </div>
        </div>
    )
}
