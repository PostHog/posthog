import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'
import { isMobile } from 'lib/utils/dom'

export interface TraceTreeKeyLegendProps {
    /** Whether the N and P keys step between traces here. */
    showTraceKeys: boolean
}

export function TraceTreeKeyLegend({ showTraceKeys }: TraceTreeKeyLegendProps): JSX.Element | null {
    // A key badge renders nothing on a phone, which would leave the words alone.
    if (isMobile()) {
        return null
    }
    return (
        <div
            className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-t border-primary px-2.5 py-1.5 text-xs text-secondary"
            data-attr="trace-view-tree-key-legend"
        >
            <span className="flex items-center gap-1">
                <KeyboardShortcut j />
                <KeyboardShortcut k />
                steps
            </span>
            {showTraceKeys ? (
                <span className="flex items-center gap-1">
                    <KeyboardShortcut n />
                    <KeyboardShortcut p />
                    traces
                </span>
            ) : null}
        </div>
    )
}
