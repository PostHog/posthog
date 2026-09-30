import { IconWarning } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { TimelineRowData } from '../types'
import { formatLatencyMs } from './formatStats'
import { NODE_KIND_COLORS } from './nodeKindColors'
import { NodeKindGlyph } from './NodeKindGlyph'
import { timelineBarGeometry } from './timelineBarGeometry'
import { TimelineTick } from './timelineTicks'

export const TIMELINE_COLUMNS = 'grid-cols-[minmax(8rem,14rem)_1fr]'

const ERROR_BAR_COLORS = { barBg: 'bg-danger-highlight', barBorder: 'border-danger' }

export interface TimelineRowProps {
    row: TimelineRowData
    totalMs: number
    ticks: TimelineTick[]
    isSelected: boolean
    onSelect: () => void
}

export function TimelineRow({ row, totalMs, ticks, isSelected, onSelect }: TimelineRowProps): JSX.Element {
    const { leftPercent, widthPercent } = timelineBarGeometry(row.startMs, row.durationMs ?? 0, totalMs)
    const barColors = row.hasError ? ERROR_BAR_COLORS : NODE_KIND_COLORS[row.kind]
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
                <span className={cn('truncate', row.hasError && 'text-danger')}>{row.name}</span>
                {row.hasError ? <IconWarning className="shrink-0 text-danger" role="img" aria-label="Error" /> : null}
            </span>
            <span className="relative h-6">
                {ticks.map((tick) => (
                    <span
                        key={tick.valueMs}
                        aria-hidden
                        className="absolute inset-y-0 w-px bg-[var(--color-border-primary)]"
                        style={{ left: `${tick.fraction * 100}%` }}
                    />
                ))}
                {row.durationMs === null ? (
                    <>
                        <span
                            aria-hidden
                            title="Latency unknown"
                            className={cn(
                                'absolute top-1/2 ml-0.5 size-2 -translate-y-1/2 rotate-45 border',
                                barColors.barBg,
                                barColors.barBorder
                            )}
                            style={{ left: `${leftPercent}%` }}
                        />
                        <span className="sr-only">Latency unknown</span>
                    </>
                ) : (
                    <span
                        className={cn(
                            'absolute top-1 bottom-1 truncate rounded-sm border px-1 font-mono text-xxs leading-4',
                            barColors.barBg,
                            barColors.barBorder
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
