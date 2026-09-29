import { cn } from 'lib/utils/css-classes'

import { TimelineRowData } from '../types'
import { formatLatencyMs } from './formatStats'
import { NODE_KIND_COLORS } from './nodeKindColors'
import { NodeKindGlyph } from './NodeKindGlyph'
import { timelineBarGeometry } from './timelineBarGeometry'

export const TIMELINE_COLUMNS = 'grid-cols-[minmax(8rem,14rem)_1fr]'

export interface TimelineRowProps {
    row: TimelineRowData
    totalMs: number
    isSelected: boolean
    onSelect: () => void
}

export function TimelineRow({ row, totalMs, isSelected, onSelect }: TimelineRowProps): JSX.Element {
    const { leftPercent, widthPercent } = timelineBarGeometry(row.startMs, row.durationMs ?? 0, totalMs)
    const kindColors = NODE_KIND_COLORS[row.kind]
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
                {row.durationMs === null ? (
                    <>
                        <span
                            aria-hidden
                            title="Latency unknown"
                            className={cn(
                                'absolute top-1/2 ml-0.5 size-2 -translate-y-1/2 rotate-45 border',
                                kindColors.barBg,
                                kindColors.barBorder
                            )}
                            style={{ left: `${leftPercent}%` }}
                        />
                        <span className="sr-only">Latency unknown</span>
                    </>
                ) : (
                    <span
                        className={cn(
                            'absolute top-1 bottom-1 truncate rounded-sm border px-1 font-mono text-xxs leading-4',
                            kindColors.barBg,
                            kindColors.barBorder
                        )}
                        style={{
                            left: `${leftPercent}%`,
                            width: `${widthPercent}%`,
                        }}
                    >
                        {formatLatencyMs(row.durationMs)}
                    </span>
                )}
            </span>
        </button>
    )
}
