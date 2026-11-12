import type {
    TraceFeedbackApi,
    TraceNodeApi,
    TraceStepFeedbackApi,
    TraceTimelineRowApi,
} from '../../../generated/api.schemas'
import {
    ConversationState,
    EvalRollupOutcome,
    FeedbackStepContext,
    LabeledLink,
    LoadFailure,
    TraceMode,
} from '../types'
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
    evalOutcomes: ReadonlyMap<string, EvalRollupOutcome>
    /** The steps that contain the search query, or null when nothing is searched. */
    matchingNodeIds?: ReadonlySet<string> | null
    highlightQuery?: string | null
    /** Changes on each step to a match, which scrolls the selected step and its first highlight into view. */
    matchStepCount?: number
    summaryMode: SummaryModeViewProps
    /** Null until the feedback has loaded. */
    feedback: TraceFeedbackApi | null
    feedbackFailed: boolean
    feedbackSteps: FeedbackStepContext
    onRetryFeedback?: () => void
    /** Null until the feedback has loaded. */
    feedbackCount?: number | null
    /** Feedback entries per step id, trace-level ones on the root. */
    stepFeedback?: ReadonlyMap<string, TraceStepFeedbackApi>
}

export type TraceViewProps =
    | { status: 'loading' }
    | { status: 'error'; loadFailure: LoadFailure; backLink: LabeledLink | null }
    | ({ status: 'ready' } & TraceViewReadyProps)

export function TraceView(props: TraceViewProps): JSX.Element {
    if (props.status === 'loading') {
        return <TraceViewLoading />
    }
    if (props.status === 'error') {
        return <TraceViewError loadFailure={props.loadFailure} backLink={props.backLink} />
    }
    return (
        <div className="flex min-h-0 flex-1 flex-col gap-4">
            <TraceHeader {...props.header} search={props.search} />
            <TraceSummaryBar {...props.summary} />
            <TraceModeTabs mode={props.mode} onModeChange={props.onModeChange} feedbackCount={props.feedbackCount} />
            <div className="min-h-0 flex-1 overflow-y-auto">
                {props.mode === 'spans' ? (
                    <TraceSplitView
                        tree={props.tree}
                        selectedNodeId={props.selectedNodeId}
                        onSelectNode={props.onSelectNode}
                        onPrefetchNode={props.onPrefetchNode}
                        detail={props.detail}
                        evalOutcomes={props.evalOutcomes}
                        stepFeedback={props.stepFeedback}
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
                        feedback={props.feedback}
                        failed={props.feedbackFailed}
                        steps={props.feedbackSteps}
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
        </div>
    )
}
