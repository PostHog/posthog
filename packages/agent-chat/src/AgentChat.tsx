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

import { ArrowUpIcon } from 'lucide-react'
import { useId, useState } from 'react'
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
    onSend?: (text: string) => void
    onApprove?: (callId: string) => void
    onDeny?: (callId: string) => void
    onReconnect?: () => void
    onExitPlayground?: () => void
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
}: AgentChatProps): React.ReactElement {
    const [draft, setDraft] = useState('')
    const inputId = useId()

    const sending = session.state === 'streaming' || session.state === 'awaiting_client_tool'
    const inputDisabled = sending || session.state === 'awaiting_approval' || session.state === 'error'
    const waiting = session.turns.length === 0
    const effectivePrompts = starterPrompts ?? getStarterPrompts(context)

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
            />

            <div className="flex-1 overflow-y-auto">
                {waiting ? (
                    <WaitingState context={context} starterPrompts={effectivePrompts} onStart={send} />
                ) : (
                    <div className="space-y-3 px-4 py-4">
                        {session.turns.map((turn) => (
                            <TurnRow key={turn.id} turn={turn} />
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
        return 'Working…'
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
        <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {message}
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
                <span>{sending ? 'streaming…' : 'Enter to send · Shift+Enter for newline'}</span>
                <span>${usage.costUsd.toFixed(3)}</span>
            </div>
        </div>
    )
}
