import { cn } from 'lib/utils/css-classes'

import { TimelineRowData, TraceNodeKind } from '../types'
import { formatLatencyMs } from './formatStats'
import { NodeKindGlyph } from './NodeKindGlyph'

export const TIMELINE_COLUMNS = 'grid-cols-[minmax(8rem,14rem)_1fr]'

const BAR_COLORS: Record<TraceNodeKind, string> = {
    trace: 'bg-[var(--data-color-1)]/20 border-[var(--data-color-1)]/60',
    span: 'bg-[var(--data-color-8)]/20 border-[var(--data-color-8)]/60',
    generation: 'bg-[var(--data-color-14)]/25 border-[var(--data-color-14)]/60',
    embedding: 'bg-[var(--data-color-11)]/25 border-[var(--data-color-11)]/60',
}

// Keeps instant events visible as a sliver instead of a zero-width bar.
const MIN_BAR_PERCENT = 1.5

export interface TimelineRowProps {
    row: TimelineRowData
    totalMs: number
    isSelected: boolean
    onSelect: () => void
}

export function TimelineRow({ row, totalMs, isSelected, onSelect }: TimelineRowProps): JSX.Element {
    const safeTotal = totalMs > 0 ? totalMs : 1
    const left = Math.min((row.startMs / safeTotal) * 100, 100 - MIN_BAR_PERCENT)
    const width = Math.max((row.durationMs / safeTotal) * 100, MIN_BAR_PERCENT)
    return (
        <button
            type="button"
            onClick={onSelect}
            data-attr="trace-view-timeline-row"
            className={cn(
                'grid w-full items-center border-b border-primary text-left hover:bg-fill-button-tertiary-hover',
                TIMELINE_COLUMNS,
                isSelected && 'bg-fill-button-tertiary-active'
            )}
        >
            <span
                className="flex min-w-0 items-center gap-1.5 py-1 pr-2 text-sm"
                style={{ paddingLeft: `${0.5 + row.depth * 0.625}rem` }}
            >
                <NodeKindGlyph kind={row.kind} />
                <span className="truncate">{row.name}</span>
            </span>
            <span className="relative h-6 bg-[linear-gradient(to_right,var(--color-border-primary)_1px,transparent_1px)] bg-[length:25%_100%]">
                <span
                    className={cn(
                        'absolute top-1 bottom-1 truncate rounded-sm border px-1 font-mono text-xxs leading-4',
                        BAR_COLORS[row.kind]
                    )}
                    style={{ left: `${left}%`, width: `${Math.min(width, 100 - left)}%` }}
                >
                    {formatLatencyMs(row.durationMs)}
                </span>
            </span>
        </button>
    )
}
