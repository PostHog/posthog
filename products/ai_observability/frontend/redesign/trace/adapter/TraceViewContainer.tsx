import { useActions, useMountedLogic, useValues } from 'kea'
import { memo, useEffect } from 'react'

import { SaveToDatasetButton } from '../../../datasets/SaveToDatasetButton'
import { saveToDatasetButtonLogic } from '../../../datasets/saveToDatasetButtonLogic'
import type { TraceApi } from '../../../generated/api.schemas'
import { TraceSummaryBarProps } from '../components/TraceSummaryBar'
import { TraceView, TraceViewProps, TraceViewReadyProps } from '../components/TraceView'
import { traceExportLogic } from '../traceExportLogic'
import { traceMessagesOpeningLogic } from '../traceMessagesOpeningLogic'
import { traceReviewLogic, traceReviewLogicValues } from '../traceReviewLogic'
import { traceViewModelLogic, traceViewModelLogicValues } from '../traceViewModelLogic'
import {
    FeedbackEntry,
    LabeledLink,
    MatchDirection,
    MessagesOpening,
    NodeDetailTab,
    SummaryItemKind,
    TraceMode,
} from '../types'
import { confirmRemoveFromQueue } from './confirmRemoveFromQueue'
import { TraceReviewActions } from './TraceReviewActions'
import { traceReviewBridgeLogic } from './traceReviewBridgeLogic'

export interface TraceViewContainerProps {
    hostId: string
    traceId: string
    timestampHint: string | null
    backLink: LabeledLink | null
}

type ReadyValues = Pick<
    traceViewModelLogicValues,
    | 'trace'
    | 'clusters'
    | 'evaluationResults'
    | 'traceFeedback'
    | 'pullRequest'
    | 'mode'
    | 'tree'
    | 'selectedNodeId'
    | 'selectedTreeNode'
    | 'selectedNodeLoad'
    | 'evaluationResultsFailed'
    | 'detailTab'
    | 'createdAt'
    | 'datasetsEnabled'
    | 'selectedRaw'
    | 'canViewInThread'
    | 'thread'
    | 'timeline'
    | 'evalOutcomes'
    | 'searchBox'
    | 'matchingNodeIds'
    | 'highlightQuery'
    | 'matchStepCount'
    | 'summaryState'
    | 'summaryRequesting'
    | 'summaryRequestError'
    | 'summaryConsentGiven'
    | 'feedbackCount'
    | 'stepFeedback'
    | 'traceFeedbackFailed'
    | 'stepLabels'
    | 'feedbackFocusNodeId'
    | 'selectedStepFeedback'
> &
    Pick<
        traceReviewLogicValues,
        'reviewStatus' | 'reviewStatusFailed' | 'queueHref' | 'canEditReviews' | 'removeFromQueueLoading'
    > & {
        traceId: string
        traceExportLoading: boolean
        traceCopying: boolean
        backLink: LabeledLink | null
        messagesOpening: MessagesOpening
    }

interface ReadyActions {
    setMode: (mode: TraceMode) => void
    selectNode: (id: string) => void
    selectAndShowSpans: (id: string) => void
    setDetailTab: (tab: NodeDetailTab) => void
    viewInThread: () => void
    prefetchNode: (id: string) => void
    exportTrace: () => void
    copyTrace: () => void
    showFailingEvals: () => void
    setQuery: (query: string) => void
    stepMatch: (direction: MatchDirection) => void
    summarize: () => void
    regenerateSummary: () => void
    loadSummary: () => void
    summaryStepClicked: (nodeId: string, kind: SummaryItemKind) => void
    showFeedback: (nodeId: string | null, entry: FeedbackEntry) => void
    retryTraceFeedback: () => void
    loadReviewStatus: () => void
    removeFromQueue: () => void
    setMessagesOpening: (opening: MessagesOpening) => void
}

function toSummaryProps(trace: TraceApi, values: ReadyValues, actions: ReadyActions): TraceSummaryBarProps {
    const queue = values.reviewStatus?.queue ?? null
    return {
        trace,
        clusters: values.clusters,
        evals: values.evaluationResults
            ? { summary: values.evaluationResults.summary, onClick: actions.showFailingEvals }
            : null,
        feedback: values.traceFeedback
            ? { summary: values.traceFeedback.summary, onClick: () => actions.showFeedback(null, 'chip') }
            : null,
        git: trace.git ? { ...trace.git, pullRequest: values.pullRequest } : null,
        review: values.reviewStatus
            ? {
                  status: values.reviewStatus,
                  queueHref: values.queueHref,
                  onRemoveFromQueue:
                      values.canEditReviews && queue && !values.removeFromQueueLoading
                          ? () => confirmRemoveFromQueue(queue.name, actions.removeFromQueue)
                          : null,
              }
            : null,
    }
}

function toReadyProps(values: ReadyValues, actions: ReadyActions): TraceViewReadyProps | null {
    const { trace } = values
    if (!trace) {
        return null
    }
    return {
        header: {
            name: trace.name,
            hasError: trace.hasError,
            backLink: values.backLink,
            copyAction: { loading: values.traceCopying, onCopy: actions.copyTrace },
            exportAction: { loading: values.traceExportLoading, onExport: actions.exportTrace },
            actions: (
                <TraceReviewActions
                    traceId={values.traceId}
                    status={values.reviewStatus}
                    failed={values.reviewStatusFailed}
                    onQueueChanged={actions.loadReviewStatus}
                />
            ),
        },
        summary: toSummaryProps(trace, values, actions),
        mode: values.mode,
        onModeChange: actions.setMode,
        tree: values.tree,
        selectedNodeId: values.selectedNodeId,
        onSelectNode: actions.selectNode,
        onPrefetchNode: actions.prefetchNode,
        onSelectFromView: actions.selectAndShowSpans,
        detail: values.selectedTreeNode
            ? {
                  node: values.selectedTreeNode,
                  load: values.selectedNodeLoad,
                  trace,
                  evaluationResults: values.evaluationResults?.results ?? null,
                  evaluationResultsFailed: values.evaluationResultsFailed,
                  stepLabels: values.stepLabels,
                  raw: values.selectedRaw,
                  tab: values.detailTab,
                  onTabChange: actions.setDetailTab,
                  onViewInThread: values.canViewInThread ? actions.viewInThread : null,
                  messagesOpening: values.messagesOpening,
                  onMessagesOpeningChange: actions.setMessagesOpening,
                  actions:
                      values.datasetsEnabled && values.createdAt ? (
                          <SaveToDatasetButton
                              key={values.selectedNodeId}
                              step={{
                                  traceId: values.traceId,
                                  nodeId: values.selectedNodeId,
                                  timestamp: values.createdAt,
                              }}
                          />
                      ) : null,
                  stepFeedback: values.selectedStepFeedback
                      ? {
                            feedback: values.selectedStepFeedback,
                            onOpen: () => actions.showFeedback(values.selectedNodeId, 'step'),
                        }
                      : null,
              }
            : null,
        thread: values.thread,
        timeline: values.timeline,
        evalOutcomes: values.evalOutcomes,
        search: { ...values.searchBox, onQueryChange: actions.setQuery, onStep: actions.stepMatch },
        matchingNodeIds: values.matchingNodeIds,
        highlightQuery: values.highlightQuery,
        matchStepCount: values.matchStepCount,
        summaryMode: {
            state: values.summaryState,
            requesting: values.summaryRequesting,
            requestError: values.summaryRequestError,
            consentGiven: values.summaryConsentGiven,
            onRequest: actions.summarize,
            onRegenerate: actions.regenerateSummary,
            onReload: actions.loadSummary,
            onSelectStep: actions.summaryStepClicked,
        },
        feedback: values.traceFeedback,
        feedbackFailed: values.traceFeedbackFailed,
        feedbackSteps: {
            traceId: values.traceId,
            stepLabels: values.stepLabels,
            focusNodeId: values.feedbackFocusNodeId,
        },
        onRetryFeedback: actions.retryTraceFeedback,
        feedbackCount: values.feedbackCount,
        stepFeedback: values.stepFeedback,
    }
}

export const TraceViewContainer = memo(function TraceViewContainer({
    hostId,
    traceId,
    timestampHint,
    backLink,
}: TraceViewContainerProps): JSX.Element {
    const logic = traceViewModelLogic({ hostId, traceId, timestampHint })
    // Every kea value getter is a hook, so read them all on every render, whatever the status.
    const {
        status,
        loadFailure,
        trace,
        clusters,
        evaluationResults,
        traceFeedback,
        pullRequest,
        mode,
        tree,
        selectedNodeId,
        selectedTreeNode,
        selectedNodeLoad,
        evaluationResultsFailed,
        detailTab,
        createdAt,
        datasetsEnabled,
        selectedRaw,
        canViewInThread,
        thread,
        timeline,
        evalOutcomes,
        searchBox,
        matchingNodeIds,
        highlightQuery,
        matchStepCount,
        summaryState,
        summaryRequesting,
        summaryRequestError,
        summaryConsentGiven,
        feedbackCount,
        stepFeedback,
        traceFeedbackFailed,
        stepLabels,
        feedbackFocusNodeId,
        selectedStepFeedback,
    } = useValues(logic)
    const actions = useActions(logic)
    const exportLogic = traceExportLogic({ traceId, timestampHint })
    const { traceExportLoading, traceCopying } = useValues(exportLogic)
    const { exportTrace, copyTrace } = useActions(exportLogic)
    const reviewLogic = traceReviewLogic({ traceId })
    const { reviewStatus, reviewStatusFailed, queueHref, canEditReviews, removeFromQueueLoading } =
        useValues(reviewLogic)
    const { loadReviewStatus, removeFromQueue } = useActions(reviewLogic)
    useMountedLogic(traceReviewBridgeLogic({ traceId }))
    // The dataset button remounts on every step change. Its logic has no key, so it would refetch datasets and recents
    // on every remount without this mount.
    useEffect(() => (datasetsEnabled ? saveToDatasetButtonLogic.mount() : undefined), [datasetsEnabled])
    const { messagesOpening } = useValues(traceMessagesOpeningLogic)
    const { setMessagesOpening } = useActions(traceMessagesOpeningLogic)

    const readyProps =
        status === 'ready'
            ? toReadyProps(
                  {
                      trace,
                      clusters,
                      evaluationResults,
                      traceFeedback,
                      pullRequest,
                      mode,
                      tree,
                      selectedNodeId,
                      selectedTreeNode,
                      selectedNodeLoad,
                      evaluationResultsFailed,
                      detailTab,
                      createdAt,
                      datasetsEnabled,
                      selectedRaw,
                      canViewInThread,
                      thread,
                      timeline,
                      evalOutcomes,
                      searchBox,
                      matchingNodeIds,
                      highlightQuery,
                      matchStepCount,
                      summaryState,
                      summaryRequesting,
                      summaryRequestError,
                      summaryConsentGiven,
                      feedbackCount,
                      stepFeedback,
                      traceFeedbackFailed,
                      stepLabels,
                      feedbackFocusNodeId,
                      selectedStepFeedback,
                      traceExportLoading,
                      traceCopying,
                      backLink,
                      traceId,
                      reviewStatus,
                      reviewStatusFailed,
                      queueHref,
                      canEditReviews,
                      removeFromQueueLoading,
                      messagesOpening,
                  },
                  { ...actions, exportTrace, copyTrace, loadReviewStatus, removeFromQueue, setMessagesOpening }
              )
            : null

    const props: TraceViewProps = readyProps
        ? { status: 'ready', ...readyProps }
        : status === 'error' && loadFailure
          ? { status: 'error', loadFailure, backLink }
          : { status: 'loading' }

    return <TraceView {...props} />
})
