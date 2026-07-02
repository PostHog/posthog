import { useMemo, useState } from 'react'

import { IconChevronDown, IconExpand45 } from '@posthog/icons'
import { LemonButton, LemonModal, Tooltip } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { cn } from 'lib/utils/css-classes'

import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { TraceBarKind, TraceTimelineBar, buildTicks, buildTraceTimeline, formatDuration } from './buildTraceTimeline'

// Same hues as the tree's EventTypeTag: generation green, embedding amber,
// span neutral, trace purple. Opaque fills so the gridlines don't show through
// the bars; selecting a bar amplifies its own hue with a ring, and an error
// swaps the border to red (amplified the same way when selected).
const KIND_BAR: Record<TraceBarKind, { fill: string; border: string; ring: string }> = {
    generation: { fill: 'bg-fill-success-secondary text-success', border: 'border-success', ring: 'ring-success' },
    span: { fill: 'bg-fill-secondary text-secondary', border: 'border-primary', ring: 'ring-[var(--border-bold)]' },
    embedding: { fill: 'bg-fill-warning-secondary text-warning', border: 'border-warning', ring: 'ring-warning' },
    trace: { fill: 'bg-fill-secondary text-purple', border: 'border-purple', ring: 'ring-[var(--purple)]' },
}

const BAR_H = 16
// Wide enough for the nesting connectors drawn in the gap to stay legible.
const LANE_GAP = 6
const LANE_H = BAR_H + LANE_GAP
// Beyond this many lanes the chart scrolls vertically instead of growing, so a
// deeply nested trace can't crowd out the rest of the page.
const MAX_VISIBLE_LANES = 6

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
    const [isFullScreen, setIsFullScreen] = useState(false)
    const { bars, totalMs, laneCount } = useMemo(() => buildTraceTimeline(events), [events])
    // One └ hook per parent per row, anchored at that row's first child — a row
    // of siblings shares a single connector instead of one hook per bar.
    const elbows = useMemo(() => {
        const barById = new Map(bars.map((b) => [b.id, b]))
        const seen = new Set<string>()
        const result: { child: TraceTimelineBar; parent: TraceTimelineBar }[] = []
        // bars are sorted by lane then startMs, so the first hit per key is the
        // row's earliest child.
        for (const bar of bars) {
            const parent = bar.parentEventId ? barById.get(bar.parentEventId) : undefined
            if (!parent || parent.lane >= bar.lane) {
                continue
            }
            const key = `${bar.parentEventId}:${bar.lane}`
            if (!seen.has(key)) {
                seen.add(key)
                result.push({ child: bar, parent })
            }
        }
        return result
    }, [bars])

    // Nothing to draw without at least one bar of nonzero width.
    if (!bars.length || totalMs <= 0) {
        return null
    }

    const ticks = buildTicks(totalMs)
    const presentKinds = Array.from(new Set(bars.map((b) => b.kind)))
    const hasErrors = bars.some((b) => b.isError)
    const pct = (ms: number): number => (ms / totalMs) * 100
    const chartHeight = laneCount * LANE_H - LANE_GAP

    // Rendered inline (capped height) and inside the full-screen modal (viewport height).
    const renderCanvas = (maxHeight: number | string): JSX.Element => (
        <div className="px-3 pb-2">
            <div className="relative h-4 mb-1.5 text-[10px] leading-4 text-muted">
                {ticks.map((tick) => (
                    <span
                        key={tick}
                        className={cn('absolute whitespace-nowrap', tick > 0 && '-translate-x-1/2')}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ left: `${pct(tick)}%` }}
                    >
                        {formatDuration(tick)}
                    </span>
                ))}
            </div>
            {/* The negative margin + matching padding move the clip edge out by
                        2px without shifting the canvas, so the outer state rings on bars
                        at the chart's edges don't get clipped. The scroll shadows signal
                        when more lanes hide beyond the height cap. */}
            <ScrollableShadows
                direction="vertical"
                className="-m-0.5"
                innerClassName="p-0.5"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ maxHeight }}
            >
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div className="relative" style={{ height: chartHeight }}>
                    {ticks.slice(1).map((tick) => (
                        <div
                            key={tick}
                            aria-hidden
                            className="absolute top-0 bottom-0 border-l border-primary opacity-60"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ left: `${pct(tick)}%` }}
                        />
                    ))}
                    {elbows.map(({ child, parent }) => {
                        const elbowTop = parent.lane * LANE_H + BAR_H + 1
                        return (
                            // └-shaped elbow from the parent's underside into the
                            // row's first child, directory-tree style.
                            <div
                                key={`elbow-${child.id}`}
                                aria-hidden
                                className="absolute w-1 rounded-bl-sm border-l border-b border-border-bold"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{
                                    left: `calc(${pct(child.startMs)}% - 4px)`,
                                    top: elbowTop,
                                    height: child.lane * LANE_H + BAR_H / 2 - elbowTop,
                                }}
                            />
                        )
                    })}
                    {bars.map((bar) => {
                        const isInstant = bar.durationMs <= 0
                        const selected = selectedEventId === bar.id
                        const dur = isInstant ? undefined : formatDuration(bar.durationMs)
                        const tooltip = [bar.label, dur, bar.isError ? 'error' : undefined].filter(Boolean).join(' · ')
                        return (
                            <Tooltip key={bar.id} title={tooltip}>
                                <button
                                    type="button"
                                    onClick={() => onSelectEvent(bar.id)}
                                    aria-label={tooltip}
                                    className={cn(
                                        'absolute flex items-center overflow-hidden rounded-[3px] border cursor-pointer',
                                        KIND_BAR[bar.kind].fill,
                                        bar.isError ? 'border-danger' : KIND_BAR[bar.kind].border,
                                        selected && [
                                            'ring-2 z-10',
                                            bar.isError ? 'ring-danger' : KIND_BAR[bar.kind].ring,
                                        ]
                                    )}
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{
                                        left: `${pct(bar.startMs)}%`,
                                        width: isInstant ? 3 : `max(${pct(bar.durationMs)}%, 3px)`,
                                        top: bar.lane * LANE_H,
                                        height: BAR_H,
                                    }}
                                    data-attr="trace-timeline-bar"
                                >
                                    {/* Truncates to the bar; the padding swallows it entirely on
                                                slivers. The tooltip always carries the full text. */}
                                    {!isInstant && (
                                        <span className="px-1 text-[10px] leading-none font-medium truncate">
                                            {bar.label} <span className="opacity-70">{dur}</span>
                                        </span>
                                    )}
                                </button>
                            </Tooltip>
                        )
                    })}
                </div>
            </ScrollableShadows>
        </div>
    )

    return (
        <div className="border rounded bg-surface-primary shrink-0" data-attr="trace-timeline">
            <div className="flex items-center gap-2 px-2 py-1">
                <LemonButton
                    size="xsmall"
                    icon={<IconChevronDown className={cn('transition-transform', collapsed && '-rotate-90')} />}
                    onClick={() => setCollapsed((c) => !c)}
                    aria-label={collapsed ? 'Expand timeline' : 'Collapse timeline'}
                />
                <span className="text-sm font-semibold">
                    Timeline <span className="text-muted font-normal">({formatDuration(totalMs)})</span>
                </span>
                <div className="flex-1" />
                {!collapsed && (
                    <div className="hidden sm:flex items-center gap-3 pr-1 text-xs text-muted">
                        {presentKinds.map((kind) => (
                            <span key={kind} className="flex items-center gap-1">
                                <span
                                    className={cn(
                                        'w-2.5 h-2.5 rounded-[3px] border',
                                        KIND_BAR[kind].fill,
                                        KIND_BAR[kind].border
                                    )}
                                />
                                {kind}
                            </span>
                        ))}
                        {hasErrors && (
                            <span className="flex items-center gap-1">
                                <span className="w-2.5 h-2.5 rounded-[3px] border border-danger bg-fill-secondary" />
                                error
                            </span>
                        )}
                    </div>
                )}
                <LemonButton
                    size="xsmall"
                    icon={<IconExpand45 />}
                    onClick={() => setIsFullScreen(true)}
                    tooltip="Expand timeline"
                    aria-label="Expand timeline full screen"
                />
            </div>
            {!collapsed && renderCanvas(MAX_VISIBLE_LANES * LANE_H - LANE_GAP + 4)}
            <LemonModal
                isOpen={isFullScreen}
                onClose={() => setIsFullScreen(false)}
                fullScreen
                title={`Timeline (${formatDuration(totalMs)})`}
            >
                {renderCanvas('calc(100vh - 11rem)')}
            </LemonModal>
        </div>
    )
}
