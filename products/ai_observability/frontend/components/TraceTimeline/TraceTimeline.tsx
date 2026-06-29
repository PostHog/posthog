import { Fragment, useState } from 'react'

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

// Overlapping bars stack into lanes. Each lane row is a colored bar (`h-5`) plus
// a caption line beneath it; LANE_GAP keeps stacked rows from touching.
const BAR_H = 20
const CAPTION_H = 12
const BAR_CAPTION_GAP = 2
const LANE_GAP = 10
const ROW_H = BAR_H + BAR_CAPTION_GAP + CAPTION_H

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
                        style={{ height: laneCount * ROW_H + (laneCount - 1) * LANE_GAP }}
                    >
                        {bars.map((bar) => {
                            const startPct = pct(bar.startMs)
                            const widthPct = Math.max(pct(bar.durationMs), 0.5)
                            const selected = selectedEventId === bar.id
                            const dur = humanFriendlyMilliseconds(bar.durationMs)
                            const barTop = bar.lane * (ROW_H + LANE_GAP)
                            return (
                                <Fragment key={bar.id}>
                                    <Tooltip title={`${bar.label} · ${dur}`}>
                                        <button
                                            type="button"
                                            onClick={() => onSelectEvent(bar.id)}
                                            aria-label={`${bar.label}, ${dur}`}
                                            className={cn(
                                                'absolute h-5 rounded-sm cursor-pointer',
                                                KIND_CLASS[bar.kind],
                                                bar.isError && 'ring-2 ring-danger',
                                                selected && 'outline outline-2 outline-offset-1 outline-purple z-10'
                                            )}
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={{ left: `${startPct}%`, width: `${widthPct}%`, top: barTop }}
                                            data-attr="trace-timeline-bar"
                                        />
                                    </Tooltip>
                                    {/* Caption below the bar, left-aligned to its start. It truncates to the
                                        room before the next bar in the lane; the selected bar shows its full
                                        label, raised above neighbors. Full text is always in the tooltip. */}
                                    <div
                                        aria-hidden
                                        className={cn(
                                            'absolute text-[10px] leading-none whitespace-nowrap pointer-events-none',
                                            selected ? 'z-10' : 'overflow-hidden text-ellipsis'
                                        )}
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={{
                                            left: `${startPct}%`,
                                            top: barTop + BAR_H + BAR_CAPTION_GAP,
                                            maxWidth: selected
                                                ? undefined
                                                : `${Math.max(pct(bar.labelRoomMs), widthPct)}%`,
                                        }}
                                    >
                                        {bar.label} <span className="text-muted">{dur}</span>
                                    </div>
                                </Fragment>
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
