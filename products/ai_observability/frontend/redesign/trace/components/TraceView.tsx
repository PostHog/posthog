import type { TraceNodeApi, TraceTimelineRowApi } from '../../../generated/api.schemas'
import { ConversationState, EvalRollupOutcome, FeedbackModeState, LabeledLink, TraceMode } from '../types'
import { NodeDetailProps } from './NodeDetail'
import { SummaryModeView, SummaryModeViewProps } from './SummaryModeView'
import { Thread } from './Thread'
import { TraceFeedbackView } from './TraceFeedbackView'
import { TraceHeader, TraceHeaderProps } from './TraceHeader'
import { TraceModeTabs } from './TraceModeTabs'
import { TraceSearchBoxProps } from './TraceSearchBox'
import { TraceSplitView } from './TraceSplitView'
import { TraceSummaryBar, TraceSummaryBarProps } from './TraceSummaryBar'
import { TraceTimeline } from './TraceTimeline'
import { TraceViewError } from './TraceViewError'
import { TraceViewLoading } from './TraceViewLoading'

export interface TraceViewReadyProps {
    header: Omit<TraceHeaderProps, 'search'>
    summary: TraceSummaryBarProps
    mode: TraceMode
    onModeChange: (mode: TraceMode) => void
    tree: TraceNodeApi[]
    selectedNodeId: string | null
    onSelectNode: (id: string) => void
    onPrefetchNode: (id: string) => void
    onSelectFromView: (id: string) => void
    detail: Omit<NodeDetailProps, 'onSelectNode' | 'highlightQuery' | 'matchStepCount'> | null
    thread: ConversationState
    timeline: { rows: TraceTimelineRowApi[]; totalMs: number }
    search?: TraceSearchBoxProps | null
    evalOutcomes: Record<string, EvalRollupOutcome>
    /** The steps that contain the search query, or null when nothing is searched. */
    matchingNodeIds?: ReadonlySet<string> | null
    highlightQuery?: string | null
    /** Changes on each step to a match, which scrolls the selected step and its first highlight into view. */
    matchStepCount?: number
    summaryMode: SummaryModeViewProps
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
            <TraceHeader {...props.header} search={props.search} />
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
                    matchingNodeIds={props.matchingNodeIds}
                    highlightQuery={props.highlightQuery}
                    matchStepCount={props.matchStepCount}
                />
            ) : props.mode === 'thread' ? (
                <Thread
                    conversation={props.thread}
                    onSelectMessage={props.onSelectFromView}
                    highlightQuery={props.highlightQuery}
                    matchingNodeIds={props.matchingNodeIds}
                />
            ) : props.mode === 'summary' ? (
                <SummaryModeView {...props.summaryMode} />
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
                    matchingNodeIds={props.matchingNodeIds}
                />
            )}
        </div>
    )
}
