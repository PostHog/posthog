/**
 * Session detail — embedded body for the Sessions tab.
 *
 * Top: a compact stat strip + a dismiss control (the agent name /
 * session id chrome lives in the sessions-list row, no need to repeat
 * it). Below that: a single rounded card containing the
 * **Conversation** / **Logs** tabs in its header and the active pane
 * filling the remaining height.
 *
 * The two tabs are independent — clicking a tool-call card just
 * expands it inline (same behavior as the live dock). No
 * cross-jumping between tabs; if we ever want a "view in logs"
 * affordance it should be an explicit control inside the expanded
 * tool-call body, not a side effect of clicking the card.
 */

'use client'

import { LineChartIcon, XIcon } from 'lucide-react'
import { useState } from 'react'

import type { ChatSession } from '@posthog/agent-chat'
import type { LogEntry } from '@posthog/agent-chat/fixtures'
import { Tabs, TabsContent, TabsList, TabsTrigger, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { SessionLogs } from '@/components/SessionLogs'
import { SessionPlayback } from '@/components/SessionPlayback'
import { StatStrip, type StatTile } from '@/components/StatStrip'

type Pane = 'conversation' | 'logs'

export interface SessionDetailProps {
    session: ChatSession
    logs: LogEntry[]
    /** Optional close button (clears the host's `?session=` param). */
    onClose?: () => void
    /**
     * Absolute deep link to this session's trace in the team's AI observability
     * product (`$ai_trace_id` === the session id). Renders a "View in AI
     * observability" affordance; omitted when the PostHog app URL isn't resolved.
     */
    aiObservabilityTraceUrl?: string
    /** Optional refresh control rendered in the stat strip header. */
    refreshSlot?: React.ReactNode
}

export function SessionDetail({
    session,
    logs,
    onClose,
    aiObservabilityTraceUrl,
    refreshSlot,
}: SessionDetailProps): React.ReactElement {
    const [activePane, setActivePane] = useState<Pane>('conversation')

    const tiles = buildTiles(session, logs)

    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="flex shrink-0 items-center gap-1.5 px-4 pt-4">
                <StatStrip tiles={tiles} size="sm" className="flex-1" />
                {refreshSlot}
                {aiObservabilityTraceUrl ? (
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <a
                                    href={aiObservabilityTraceUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    aria-label="View trace in AI observability"
                                    className="inline-flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
                                >
                                    <LineChartIcon className="h-4 w-4" />
                                </a>
                            }
                        />
                        <TooltipContent side="left">View in AI observability ↗</TooltipContent>
                    </Tooltip>
                ) : null}
                {onClose ? (
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <button
                                    type="button"
                                    onClick={onClose}
                                    aria-label="Close session"
                                    className="inline-flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
                                >
                                    <XIcon className="h-4 w-4" />
                                </button>
                            }
                        />
                        <TooltipContent side="left">Close session</TooltipContent>
                    </Tooltip>
                ) : null}
            </div>

            <CronTriggerBadge trigger={session.trigger} />

            <div className="min-h-0 flex-1 overflow-hidden px-4 pb-4 pt-3">
                <Tabs
                    value={activePane}
                    onValueChange={(v) => setActivePane(v as Pane)}
                    className="flex h-full min-h-0 flex-col gap-0 overflow-hidden rounded-md border border-border bg-card"
                >
                    <div className="flex shrink-0 items-center gap-3 border-b border-border bg-muted/20 px-3 pr-4">
                        <TabsList variant="line">
                            <TabsTrigger value="conversation">Conversation</TabsTrigger>
                            <TabsTrigger value="logs">
                                Logs
                                {logs.length > 0 ? (
                                    <span className="ml-1.5 text-[0.6875rem] text-muted-foreground">{logs.length}</span>
                                ) : null}
                            </TabsTrigger>
                        </TabsList>
                        {activePane === 'logs' ? (
                            <span className="ml-auto text-[0.6875rem] text-muted-foreground">
                                filtered by session_id
                            </span>
                        ) : null}
                    </div>

                    <TabsContent value="conversation" className="min-h-0 flex-1 overflow-hidden">
                        <SessionPlayback session={session} bare />
                    </TabsContent>

                    <TabsContent value="logs" className="min-h-0 flex-1 overflow-hidden">
                        <SessionLogs logs={logs} sessionStartedAt={session.started_at} bare />
                    </TabsContent>
                </Tabs>
            </div>
        </div>
    )
}

/**
 * Compact "fired by <cron_name> at <fired_at>" badge for cron-triggered
 * sessions. Renders nothing when the session wasn't fired by cron (the
 * trigger field is populated by the API client's
 * `triggerMetadataToSessionTrigger` mapping; non-cron triggers don't
 * stamp `trigger_metadata` today, so they fall through to null). Manual
 * fires get a `(manual)` suffix so an operator can tell at a glance
 * which firings came from the "Fire now" button vs the scheduler.
 */
function CronTriggerBadge({ trigger }: { trigger: ChatSession['trigger'] }): React.ReactElement | null {
    if (!trigger || trigger.kind !== 'cron') {
        return null
    }
    const firedAt = new Date(trigger.firedAt)
    const firedAtLabel = Number.isFinite(firedAt.getTime())
        ? `${firedAt.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}`
        : trigger.firedAt
    return (
        <div className="shrink-0 px-4 pt-2">
            <div className="inline-flex items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2 py-1 text-[0.6875rem] text-muted-foreground">
                <span className="font-medium text-foreground">Fired by</span>
                <code className="font-mono">{trigger.cronName}</code>
                <span>at</span>
                <span title={trigger.firedAt}>{firedAtLabel}</span>
                {trigger.manual ? (
                    <span className="ml-0.5 rounded-sm bg-warning-foreground/15 px-1 text-warning-foreground">
                        manual
                    </span>
                ) : null}
            </div>
        </div>
    )
}

function buildTiles(session: ChatSession, logs: LogEntry[]): StatTile[] {
    const toolCalls = session.turns.reduce((acc, turn) => {
        if (turn.kind !== 'assistant') {
            return acc
        }
        return acc + turn.parts.filter((p) => p.kind === 'tool_call').length
    }, 0)
    const durationMs =
        session.started_at && session.ended_at
            ? new Date(session.ended_at).getTime() - new Date(session.started_at).getTime()
            : null

    const errorCount = logs.filter((e) => e.level === 'error' || e.level === 'fatal').length

    return [
        { label: 'State', value: session.state },
        { label: 'Tool calls', value: toolCalls },
        { label: 'Cost', value: `$${session.usage.costUsd.toFixed(3)}` },
        {
            label: 'Duration',
            value: durationMs !== null ? formatDuration(durationMs) : 'in flight',
        },
        ...(errorCount > 0
            ? [{ label: 'Errors', value: errorCount, tone: 'attention' as const, hint: 'in logs' }]
            : []),
    ]
}

function formatDuration(ms: number): string {
    const s = Math.floor(ms / 1000)
    if (s < 60) {
        return `${s}s`
    }
    const m = Math.floor(s / 60)
    const rem = s % 60
    return rem === 0 ? `${m}m` : `${m}m ${rem}s`
}
