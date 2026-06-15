/**
 * Single-part renderer — dispatches on `part.kind` to the right
 * atom. Shared between the live dock and the session playback so
 * features added here (new part kinds, redesigned tool-call cards,
 * markdown opt-in) light up on both surfaces.
 *
 * `textVariant` picks the visual treatment for text parts:
 *   - `'plain'` — no bubble, used by the dock and by playback's Slack
 *     thread variant where the message bubble is the parent's job.
 *   - `'bubble'` — assistant chat bubble (`rounded-2xl rounded-tl-md`
 *     with `bg-muted/40`), used by the playback's default chat
 *     transcript so consecutive messages read as a conversation.
 */

import type { AssistantTurnPart, ClientToolHandler } from '../../types'
import { isRenderHandler } from '../../types'
import { Markdown } from '../Markdown'
import { ThinkingPart } from './ThinkingPart'
import { ToolCallCard } from './ToolCallCard'

export type PartTextVariant = 'plain' | 'bubble'

/**
 * Outcome the inline UI for a render-style client tool can resolve a
 * call with. Maps 1:1 to what the host POSTs back via the ingress
 * `/client_tool_result` endpoint — `{ ok, body }` for success,
 * `{ ok: false, error }` for failure.
 */
export type ClientToolOutcome = { ok: true; body: Record<string, unknown> } | { ok: false; error: string }

export interface PartRendererProps {
    part: AssistantTurnPart
    /** Visual treatment for text parts. Default `'plain'`. */
    textVariant?: PartTextVariant
    /** Render text parts as markdown when true (otherwise as preformatted text). */
    renderMarkdown?: boolean
    /** Cross-link: tool-call card highlights when its `callId` matches. */
    highlightedCallId?: string | null
    /** Cross-link: fires when a tool-call header is clicked. */
    onSelectCallId?: (callId: string) => void
    /**
     * Optional handlers the chat surface knows about. When the part is
     * a still-pending client tool call and the matching handler is
     * render-style (`{ id, render }`), the card renders the inline UI.
     * Sync handlers are not relevant here — they're invoked by the
     * runner, not rendered.
     */
    handlers?: ClientToolHandler[]
    /**
     * Session id passed into render-style handlers so the inline UI can
     * hit per-session APIs (e.g. when a secret editor wants to confirm
     * the write landed). Optional — the renderer can ignore it.
     */
    sessionId?: string
    /**
     * Called by the inline renderer when it's ready to resolve the
     * call. Wired to the runner's `resolveClientTool(callId, outcome)`
     * in production hosts. Stories can pass a no-op or a logger.
     */
    onClientToolResolve?: (callId: string, outcome: ClientToolOutcome) => void
    /**
     * Optional host-provided summary renderer for tool-call parts.
     * Returns a node rendered between the card header and the JSON
     * drawer — used to surface clickable destination links for
     * `focus_*` tools, styled error reasons, etc. Returning `null`
     * (or omitting the prop) falls back to the bare collapsed card.
     */
    renderToolSummary?: (part: Extract<AssistantTurnPart, { kind: 'tool_call' }>) => React.ReactNode | null
}

export function PartRenderer({
    part,
    textVariant = 'plain',
    renderMarkdown = false,
    highlightedCallId,
    onSelectCallId,
    handlers,
    sessionId,
    onClientToolResolve,
    renderToolSummary,
}: PartRendererProps): React.ReactElement {
    if (part.kind === 'text') {
        if (textVariant === 'bubble') {
            // Bubble is the visual unit, so markdown / preformatted text
            // both live inside the same shell.
            return (
                <div className="whitespace-pre-wrap rounded-2xl rounded-tl-md bg-muted/40 px-3 py-2 text-sm leading-relaxed">
                    {renderMarkdown ? <Markdown>{part.text}</Markdown> : part.text}
                </div>
            )
        }
        if (renderMarkdown) {
            return (
                <div className="px-1">
                    <Markdown>{part.text}</Markdown>
                </div>
            )
        }
        return <div className="whitespace-pre-wrap px-1 text-sm leading-relaxed">{part.text}</div>
    }
    if (part.kind === 'thinking') {
        return <ThinkingPart text={part.text} />
    }

    // tool_call. If the matching handler is render-style AND the call
    // hasn't resolved yet, render the inline slot. We stop rendering it
    // once the result arrives — keeping a stale form around after the
    // agent has moved on is just visual noise.
    const inlineSlot = pendingInlineSlot({ part, handlers, sessionId, onClientToolResolve })
    const summarySlot = renderToolSummary?.(part) ?? null
    return (
        <ToolCallCard
            part={part}
            highlighted={highlightedCallId === part.callId}
            onSelectCallId={onSelectCallId}
            inlineSlot={inlineSlot}
            summarySlot={summarySlot}
        />
    )
}

function pendingInlineSlot({
    part,
    handlers,
    sessionId,
    onClientToolResolve,
}: {
    part: Extract<AssistantTurnPart, { kind: 'tool_call' }>
    handlers?: ClientToolHandler[]
    sessionId?: string
    onClientToolResolve?: (callId: string, outcome: ClientToolOutcome) => void
}): React.ReactNode | null {
    if (part.fulfillment !== 'client' || part.result !== undefined) {
        return null
    }
    const handler = handlers?.find((h) => h.id === part.toolId)
    if (!handler || !isRenderHandler(handler)) {
        return null
    }
    // Guard the resolver so a sloppy renderer can't fire twice — the
    // runner / chat reducer doesn't handle a second result for the
    // same call id gracefully and we'd rather drop the race here.
    let settled = false
    const resolve = (result: Record<string, unknown>): void => {
        if (settled || !onClientToolResolve) {
            return
        }
        settled = true
        onClientToolResolve(part.callId, { ok: true, body: result })
    }
    const reject = (reason: string): void => {
        if (settled || !onClientToolResolve) {
            return
        }
        settled = true
        onClientToolResolve(part.callId, { ok: false, error: reason })
    }
    return handler.render(part.args, {
        resolve,
        reject,
        sessionId: sessionId ?? '',
        callId: part.callId,
    })
}
