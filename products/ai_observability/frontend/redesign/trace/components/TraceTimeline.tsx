import { cn } from 'lib/utils/css-classes'

import { TimelineRowData } from '../types'
import { TimelineAxis } from './TimelineAxis'
import { TIMELINE_COLUMNS, TimelineRow } from './TimelineRow'

export interface TraceTimelineProps {
    rows: TimelineRowData[]
    totalMs: number
    selectedNodeId: string | null
    onSelectNode: (id: string) => void
}

export function TraceTimeline({ rows, totalMs, selectedNodeId, onSelectNode }: TraceTimelineProps): JSX.Element {
    if (rows.length === 0) {
        return <p className="m-0 text-secondary">This trace has no timed steps.</p>
    }
    return (
        <div className="overflow-hidden rounded border border-primary bg-surface-primary">
            <div className={cn('grid border-b border-primary', TIMELINE_COLUMNS)}>
                <span className="px-2 py-0.5 text-xs font-semibold text-secondary">Step</span>
                <TimelineAxis totalMs={totalMs} />
            </div>
            {rows.map((row) => (
                <TimelineRow
                    key={row.id}
                    row={row}
                    totalMs={totalMs}
                    isSelected={row.id === selectedNodeId}
                    onSelect={() => onSelectNode(row.id)}
                />
            ))}
        </div>
    )
}
