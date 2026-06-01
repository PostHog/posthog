/**
 * Tool-call card — collapsed header with status dot + tool id, expands
 * to show args / result JSON. Used in both the dock and the session
 * playback.
 *
 * When `inlineSlot` is provided (a render-style client tool's UI), the
 * card renders that slot prominently below the header instead of the
 * collapsed args/result drawer. The drawer stays available behind a
 * toggle for the curious. This is the "client tools as UI" path —
 * inline forms / approve buttons / pickers live here.
 *
 * `data-call-id` is set on the outer card so a parent can find and
 * scroll the matching card into view from another surface.
 */

import { ChevronDownIcon, ChevronRightIcon } from 'lucide-react'
import { useState } from 'react'

import type { AssistantTurnPart } from '../../types'
import { JsonView } from '../JsonView'
import { Labeled } from './Labeled'

type ToolCallPart = Extract<AssistantTurnPart, { kind: 'tool_call' }>

export interface ToolCallCardProps {
    part: ToolCallPart
    /** When true, the card draws an info-toned border so cross-link selection is visible. */
    highlighted?: boolean
    /** Called when the user clicks the card header — fires alongside the local expand toggle. */
    onSelectCallId?: (callId: string) => void
    /**
     * Rendered below the header when present (typically the UI a
     * render-style client tool produces). The card auto-expands its
     * drawer so the user doesn't have to click to see it; the args /
     * result JSON drops behind a "details" toggle.
     */
    inlineSlot?: React.ReactNode
    /**
     * Optional summary row rendered between the header and the args /
     * result drawer. Hosts use this to surface a rich, one-line view
     * of what the tool did — e.g. a clickable destination link for
     * `focus_*` tools, or a styled error reason for failures — so the
     * user gets useful context without expanding the JSON.
     */
    summarySlot?: React.ReactNode
}

export function ToolCallCard({
    part,
    highlighted = false,
    onSelectCallId,
    inlineSlot,
    summarySlot,
}: ToolCallCardProps): React.ReactElement {
    const hasInline = inlineSlot !== undefined && inlineSlot !== null && inlineSlot !== false
    // With an inline slot, the details drawer hides by default — the
    // slot itself is the primary thing to look at. Without one,
    // preserve the legacy behavior where the user opens the drawer.
    const [detailsOpen, setDetailsOpen] = useState(false)
    const inFlight = part.result === undefined
    const failed = part.result !== undefined && !part.result.ok
    const dotClass = inFlight ? 'bg-muted-foreground/60 animate-pulse' : failed ? 'bg-destructive' : 'bg-success'

    return (
        <div
            className={
                'rounded-md border text-xs transition-colors ' +
                (highlighted ? 'border-info bg-info/10' : 'border-border/60 bg-muted/20')
            }
            data-call-id={part.callId}
            id={`call-${part.callId}`}
        >
            <button
                type="button"
                onClick={() => {
                    setDetailsOpen((o) => !o)
                    onSelectCallId?.(part.callId)
                }}
                className="flex w-full cursor-pointer items-center gap-2 px-2.5 py-1.5 text-left"
            >
                <span className={`inline-flex h-1.5 w-1.5 shrink-0 rounded-full ${dotClass}`} aria-hidden />
                <code className="truncate font-medium">{part.toolId}</code>
                {part.fulfillment === 'client' ? (
                    <span className="text-[0.6875rem] uppercase tracking-wide text-muted-foreground">client</span>
                ) : null}
                <span className="ml-auto text-muted-foreground">
                    {detailsOpen ? (
                        <ChevronDownIcon className="h-3 w-3" />
                    ) : (
                        <ChevronRightIcon className="h-3 w-3" />
                    )}
                </span>
            </button>
            {summarySlot ? <div className="border-t border-border/60 px-2.5 py-1.5">{summarySlot}</div> : null}
            {hasInline ? <div className="border-t border-border/60 p-2.5">{inlineSlot}</div> : null}
            {detailsOpen ? (
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
