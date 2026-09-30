import { ConversationState, LabeledLink, TimelineRowData, TraceMode, TraceTreeNode } from '../types'
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
    detail: Omit<NodeDetailProps, 'onSelectNode'> | null
    thread: ConversationState
    timeline: { rows: TimelineRowData[]; totalMs: number }
}

export type TraceViewProps =
    | { status: 'loading' }
    | { status: 'error'; errorMessage: string; backLink: LabeledLink }
    | ({ status: 'ready' } & TraceViewReadyProps)

export function TraceView(props: TraceViewProps): JSX.Element {
    if (props.status === 'loading') {
        return <TraceViewLoading />
    }
    if (props.status === 'error') {
        return <TraceViewError message={props.errorMessage} backLink={props.backLink} />
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
                <Thread conversation={props.thread} onSelectMessage={props.onSelectFromView} />
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
