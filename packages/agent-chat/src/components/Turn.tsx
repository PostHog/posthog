/**
 * Conversation turn renderer. Minimal styling:
 *  - User turns: tight, no avatar bubble — just a subtle indented line.
 *  - Assistant turns: the actual content, no avatar — the dock context
 *    already tells you who's talking.
 *  - Tool calls: one-line collapsed summary by default, click to expand.
 *  - Thinking: muted aside, foldable.
 */

import { ChevronDownIcon, ChevronRightIcon } from 'lucide-react'
import { useState } from 'react'
import type { AssistantTurnPart, Turn } from '../types'
import { JsonView } from './JsonView'
import { Markdown } from './Markdown'

interface TurnProps {
    turn: Turn
    /** When true, assistant text parts render as markdown. */
    renderMarkdown?: boolean
}

export function TurnRow({ turn, renderMarkdown }: TurnProps): React.ReactElement {
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
                <PartRenderer key={i} part={part} renderMarkdown={renderMarkdown} />
            ))}
            {turn.streaming ? <StreamingDots /> : null}
        </div>
    )
}

function PartRenderer({
    part,
    renderMarkdown,
}: {
    part: AssistantTurnPart
    renderMarkdown?: boolean
}): React.ReactElement {
    if (part.kind === 'text') {
        if (renderMarkdown) {
            return (
                <div className="px-1">
                    <Markdown>{part.text}</Markdown>
                </div>
            )
        }
        return <div className="px-1 text-sm leading-relaxed whitespace-pre-wrap">{part.text}</div>
    }
    if (part.kind === 'thinking') {
        return <ThinkingPart text={part.text} />
    }
    return <ToolCallRow part={part} />
}

function ThinkingPart({ text }: { text: string }): React.ReactElement {
    const [open, setOpen] = useState(false)
    return (
        <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="flex w-full items-start gap-1.5 rounded-md px-1.5 py-1 text-left text-xs text-muted-foreground transition-colors hover:bg-muted/30"
        >
            {open ? (
                <ChevronDownIcon className="mt-0.5 h-3 w-3 shrink-0" />
            ) : (
                <ChevronRightIcon className="mt-0.5 h-3 w-3 shrink-0" />
            )}
            <span className={open ? 'whitespace-pre-wrap' : 'line-clamp-1'}>
                <span className="font-medium text-foreground/70">Thinking · </span>
                {text}
            </span>
        </button>
    )
}

function ToolCallRow({ part }: { part: Extract<AssistantTurnPart, { kind: 'tool_call' }> }): React.ReactElement {
    const [open, setOpen] = useState(false)
    const inFlight = part.result === undefined
    const failed = part.result !== undefined && !part.result.ok

    const dotClass = inFlight
        ? 'bg-muted-foreground/60 animate-pulse'
        : failed
            ? 'bg-destructive'
            : 'bg-success'

    return (
        <div className="rounded-md border border-border/60 bg-muted/20 text-xs">
            <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left"
            >
                <span className={`inline-flex h-1.5 w-1.5 shrink-0 rounded-full ${dotClass}`} aria-hidden />
                <code className="truncate font-medium">{part.toolId}</code>
                {part.fulfillment === 'client' ? (
                    <span className="text-[0.6875rem] uppercase tracking-wide text-muted-foreground">client</span>
                ) : null}
                <span className="ml-auto text-muted-foreground">
                    {open ? <ChevronDownIcon className="h-3 w-3" /> : <ChevronRightIcon className="h-3 w-3" />}
                </span>
            </button>
            {open ? (
                <div className="space-y-2 border-t border-border/60 px-2.5 py-2">
                    <Labeled label="args">
                        <JsonView value={part.args} expandToLevel={1} />
                    </Labeled>
                    {part.result !== undefined ? (
                        <Labeled label="result">
                            <JsonView value={part.result} expandToLevel={1} />
                        </Labeled>
                    ) : null}
                </div>
            ) : null}
        </div>
    )
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }): React.ReactElement {
    return (
        <div>
            <div className="mb-1 text-[0.625rem] uppercase tracking-wide text-muted-foreground">{label}</div>
            {children}
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
