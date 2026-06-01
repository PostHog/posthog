/**
 * Conversation turn renderer used by `<AgentChat>`. Minimal styling:
 *  - User turns: tight, no avatar bubble — just a subtle indented line.
 *  - Assistant turns: parts list, no avatar — the dock context already
 *    tells you who's talking.
 *
 * The per-part rendering (text / thinking / tool calls) lives in
 * `./parts/PartRenderer` so it can be reused by other transcript
 * surfaces (e.g. the agent console's session playback). New part kinds
 * or design tweaks added there light up here automatically.
 */

import type { AssistantTurnPart, ClientToolHandler, Turn } from '../types'
import type { ClientToolOutcome } from './parts'
import { PartRenderer } from './parts'

interface TurnProps {
    turn: Turn
    /** When true, assistant text parts render as markdown. */
    renderMarkdown?: boolean
    /** Forwarded to PartRenderer for inline render-style client tools. */
    handlers?: ClientToolHandler[]
    sessionId?: string
    onClientToolResolve?: (callId: string, outcome: ClientToolOutcome) => void
    /** Forwarded to PartRenderer; host-provided per-tool summary renderer. */
    renderToolSummary?: (part: Extract<AssistantTurnPart, { kind: 'tool_call' }>) => React.ReactNode | null
}

export function TurnRow({
    turn,
    renderMarkdown,
    handlers,
    sessionId,
    onClientToolResolve,
    renderToolSummary,
}: TurnProps): React.ReactElement {
    if (turn.kind === 'user') {
        const pending = turn.pending === true
        return (
            <div
                className={
                    'rounded-md px-3 py-2 text-sm leading-relaxed ' +
                    (pending ? 'border border-dashed border-border bg-muted/20 text-muted-foreground' : 'bg-muted/40')
                }
                data-slot="agent-chat-turn-user"
                data-pending={pending ? 'true' : undefined}
            >
                <div>{turn.text}</div>
                {pending ? (
                    <div className="mt-1 text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
                        Queued · sends after current turn
                    </div>
                ) : null}
            </div>
        )
    }

    return (
        <div className="space-y-2" data-slot="agent-chat-turn-assistant">
            {turn.parts.map((part, i) => (
                <PartRenderer
                    key={i}
                    part={part}
                    textVariant="plain"
                    renderMarkdown={renderMarkdown}
                    handlers={handlers}
                    sessionId={sessionId}
                    onClientToolResolve={onClientToolResolve}
                    renderToolSummary={renderToolSummary}
                />
            ))}
            {turn.streaming ? <StreamingDots /> : null}
        </div>
    )
}

function StreamingDots(): React.ReactElement {
    return (
        <div className="flex items-center gap-1 px-1 py-1" aria-label="streaming">
            <span className="h-1 w-1 animate-pulse rounded-full bg-muted-foreground" />
            <span className="h-1 w-1 animate-pulse rounded-full bg-muted-foreground [animation-delay:120ms]" />
            <span className="h-1 w-1 animate-pulse rounded-full bg-muted-foreground [animation-delay:240ms]" />
        </div>
    )
}
