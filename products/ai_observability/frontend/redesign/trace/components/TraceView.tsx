import { ConversationTurn, TimelineRowData, TraceMode, TraceTreeNode } from '../types'
import { NodeDetailProps } from './NodeDetail'
import { Thread } from './Thread'
import { TraceHeader, TraceHeaderProps } from './TraceHeader'
import { TraceModeTabs } from './TraceModeTabs'
import { TraceSplitView } from './TraceSplitView'
import { TraceSummaryBar, TraceSummaryBarProps } from './TraceSummaryBar'
import { TraceTimeline } from './TraceTimeline'
import { TraceViewError } from './TraceViewError'
import { TraceViewLoading } from './TraceViewLoading'

export interface TraceViewReadyProps {
    header: TraceHeaderProps
    summary: TraceSummaryBarProps
    mode: TraceMode
    onModeChange: (mode: TraceMode) => void
    tree: TraceTreeNode[]
    selectedNodeId: string | null
    onSelectNode: (id: string) => void
    onSelectFromView: (id: string) => void
    detail: NodeDetailProps | null
    thread: { turns: ConversationTurn[]; activeTurnId: string | null }
    timeline: { rows: TimelineRowData[]; totalMs: number }
}

export type TraceViewProps =
    | { status: 'loading' }
    | { status: 'error'; errorMessage: string; backHref: string }
    | ({ status: 'ready' } & TraceViewReadyProps)

export function TraceView(props: TraceViewProps): JSX.Element {
    if (props.status === 'loading') {
        return <TraceViewLoading />
    }
    if (props.status === 'error') {
        return <TraceViewError message={props.errorMessage} backHref={props.backHref} />
    }
    return (
        <div className="flex flex-col gap-3">
            <TraceHeader {...props.header} />
            <TraceSummaryBar {...props.summary} />
            <TraceModeTabs mode={props.mode} onModeChange={props.onModeChange} />
            {props.mode === 'spans' ? (
                <TraceSplitView
                    tree={props.tree}
                    selectedNodeId={props.selectedNodeId}
                    onSelectNode={props.onSelectNode}
                    detail={props.detail}
                />
            ) : props.mode === 'thread' ? (
                <Thread
                    turns={props.thread.turns}
                    activeTurnId={props.thread.activeTurnId}
                    onSelectMessage={props.onSelectFromView}
                />
            ) : (
                <TraceTimeline
                    rows={props.timeline.rows}
                    totalMs={props.timeline.totalMs}
                    selectedNodeId={props.selectedNodeId}
                    onSelectNode={props.onSelectFromView}
                />
            )}
        </div>
    )
}
