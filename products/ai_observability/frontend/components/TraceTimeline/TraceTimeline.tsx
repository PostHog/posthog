import { useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyMilliseconds } from 'lib/utils/durations'

import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { TraceBarKind, buildTraceTimeline } from './buildTraceTimeline'

// Mirror the trace tree's EventTypeTag colors: generation green, embedding amber,
// span neutral (transparent + light border, like the tree's default tag).
const KIND_CLASS: Record<TraceBarKind, string> = {
    generation: 'bg-success',
    span: 'border border-primary',
    embedding: 'bg-warning',
    other: 'bg-muted',
}

// Overlapping bars stack into lanes. Bar height matches `h-5`; the gap keeps
// stacked rows from touching.
const BAR_H = 20
const LANE_GAP = 8

export function TraceTimeline({
    events,
    selectedEventId,
    onSelectEvent,
}: {
    events: LLMTraceEvent[]
    selectedEventId: string | null
    onSelectEvent: (id: string) => void
}): JSX.Element | null {
    const [collapsed, setCollapsed] = useState(false)
    const { bars, totalMs, laneCount } = buildTraceTimeline(events)

    if (!bars.length || totalMs <= 0) {
        return null
    }

    const presentKinds = Array.from(new Set(bars.map((b) => b.kind)))
    const pct = (ms: number): number => (ms / totalMs) * 100

    return (
        <div className="border rounded bg-surface-primary">
            <div className="flex items-center justify-between px-3 py-2">
                <span className="text-sm font-semibold">
                    Timeline <span className="text-muted font-normal">({humanFriendlyMilliseconds(totalMs)})</span>
                </span>
                <LemonButton
                    size="xsmall"
                    icon={<IconChevronDown className={cn('transition-transform', collapsed && '-rotate-90')} />}
                    onClick={() => setCollapsed((c) => !c)}
                    aria-label={collapsed ? 'Expand timeline' : 'Collapse timeline'}
                />
            </div>
            {!collapsed && (
                <>
                    <div
                        className="relative mx-3"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ height: laneCount * BAR_H + (laneCount - 1) * LANE_GAP }}
                    >
                        {bars.map((bar) => {
                            const widthPct = Math.max(pct(bar.durationMs), 0.5)
                            const selected = selectedEventId === bar.id
                            const dur = humanFriendlyMilliseconds(bar.durationMs)
                            return (
                                <Tooltip key={bar.id} title={`${bar.label} · ${dur}`}>
                                    <button
                                        type="button"
                                        onClick={() => onSelectEvent(bar.id)}
                                        className={cn(
                                            'absolute h-5 rounded-sm cursor-pointer flex items-center overflow-hidden',
                                            KIND_CLASS[bar.kind],
                                            // solid bars get white text; the neutral span bar keeps the default dark text
                                            bar.kind !== 'span' && 'text-white',
                                            bar.isError && 'ring-2 ring-danger',
                                            selected && 'outline outline-2 outline-offset-1 outline-purple'
                                        )}
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={{
                                            left: `${pct(bar.startMs)}%`,
                                            width: `${widthPct}%`,
                                            top: bar.lane * (BAR_H + LANE_GAP),
                                        }}
                                        data-attr="trace-timeline-bar"
                                    >
                                        {widthPct > 5 ? (
                                            <span className="text-[10px] leading-none px-1 truncate">
                                                {bar.label} <span className="opacity-80">{dur}</span>
                                            </span>
                                        ) : widthPct > 2.5 ? (
                                            <span className="text-[10px] leading-none px-1 truncate">{dur}</span>
                                        ) : null}
                                    </button>
                                </Tooltip>
                            )
                        })}
                    </div>
                    <div className="flex items-center gap-3 flex-wrap px-3 pt-2.5 pb-2 text-xs text-muted">
                        {presentKinds.map((kind) => (
                            <span key={kind} className="flex items-center gap-1.5">
                                <span className={cn('w-3 h-3 rounded', KIND_CLASS[kind])} />
                                {kind}
                            </span>
                        ))}
                    </div>
                </>
            )}
        </div>
    )
}
