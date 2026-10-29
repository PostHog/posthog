import type { TraceNodeApi, TraceTimelineRowApi } from '../../../generated/api.schemas'
import { ConversationState, EvalRollupOutcome, FeedbackModeState, LabeledLink, TraceMode } from '../types'
import { NodeDetailProps } from './NodeDetail'
import { Thread } from './Thread'
import { TraceFeedbackView } from './TraceFeedbackView'
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
    tree: TraceNodeApi[]
    selectedNodeId: string | null
    onSelectNode: (id: string) => void
    onPrefetchNode: (id: string) => void
    onSelectFromView: (id: string) => void
    detail: Omit<NodeDetailProps, 'onSelectNode'> | null
    thread: ConversationState
    timeline: { rows: TraceTimelineRowApi[]; totalMs: number }
    evalOutcomes: Record<string, EvalRollupOutcome>
    feedbackMode?: FeedbackModeState
    onRetryFeedback?: () => void
    /** Null until the feedback has loaded. */
    feedbackCount?: number | null
    /** Feedback entries per step id, trace-level ones on the root. */
    feedbackCountByNodeId?: Record<string, number>
}

const FEEDBACK_LOADING: FeedbackModeState = { status: 'loading' }

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
            <TraceModeTabs mode={props.mode} onModeChange={props.onModeChange} feedbackCount={props.feedbackCount} />
            {props.mode === 'spans' ? (
                <TraceSplitView
                    tree={props.tree}
                    selectedNodeId={props.selectedNodeId}
                    onSelectNode={props.onSelectNode}
                    onPrefetchNode={props.onPrefetchNode}
                    detail={props.detail}
                    evalOutcomes={props.evalOutcomes}
                    feedbackCountByNodeId={props.feedbackCountByNodeId}
                />
            ) : props.mode === 'thread' ? (
                <Thread conversation={props.thread} onSelectMessage={props.onSelectFromView} />
            ) : props.mode === 'feedback' ? (
                <TraceFeedbackView
                    state={props.feedbackMode ?? FEEDBACK_LOADING}
                    onSelectStep={props.onSelectFromView}
                    onRetry={props.onRetryFeedback}
                />
            ) : (
                <TraceTimeline
                    rows={props.timeline.rows}
                    totalMs={props.timeline.totalMs}
                    selectedNodeId={props.selectedNodeId}
                    onSelectNode={props.onSelectFromView}
                    onPrefetchNode={props.onPrefetchNode}
                />
            )}
        </div>
    )
}
