import { useActions, useValues } from 'kea'
import { memo, useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SaveToDatasetButton } from '../../../datasets/SaveToDatasetButton'
import { saveToDatasetButtonLogic } from '../../../datasets/saveToDatasetButtonLogic'
import type { TraceApi } from '../../../generated/api.schemas'
import { TraceSummaryBarProps } from '../components/TraceSummaryBar'
import { TraceView, TraceViewProps, TraceViewReadyProps } from '../components/TraceView'
import { traceClustersLogic, traceClustersLogicValues } from '../traceClustersLogic'
import { traceExportLogic } from '../traceExportLogic'
import { traceFeedbackLogic, traceFeedbackLogicValues } from '../traceFeedbackLogic'
import { traceGitPullRequestLogic, traceGitPullRequestLogicValues } from '../traceGitPullRequestLogic'
import { traceMessagesOpeningLogic } from '../traceMessagesOpeningLogic'
import { traceReviewLogic, traceReviewLogicValues } from '../traceReviewLogic'
import { traceSearchLogic, traceSearchLogicValues } from '../traceSearchLogic'
import { traceSummaryLogic } from '../traceSummaryLogic'
import { traceViewLogic, traceViewLogicValues } from '../traceViewLogic'
import { traceViewModelLogic, traceViewModelLogicValues } from '../traceViewModelLogic'
import {
    FeedbackEntry,
    LabeledLink,
    MatchDirection,
    MessagesOpening,
    SummaryModeState,
    SummaryRequestError,
    NodeDetailTab,
    SummaryItemKind,
    TraceMode,
} from '../types'
import { confirmRemoveFromQueue } from './confirmRemoveFromQueue'
import { TraceReviewActions } from './TraceReviewActions'

export interface TraceViewContainerProps {
    hostId: string
    traceId: string
    timestampHint: string | null
    backLink: LabeledLink | null
}

type ReadyValues = Pick<
    traceViewModelLogicValues,
    | 'trace'
    | 'mode'
    | 'selectedNodeId'
    | 'selectedTreeNode'
    | 'selectedNodeLoad'
    | 'detailTab'
    | 'selectedRaw'
    | 'canViewInThread'
    | 'thread'
    | 'searchBox'
    | 'matchStepCount'
    | 'feedbackFocusNodeId'
    | 'selectedStepFeedback'
> &
    Pick<
        traceViewLogicValues,
        'evaluationResults' | 'evaluationResultsFailed' | 'createdAt' | 'evalOutcomes' | 'stepLabels'
    > &
    Pick<traceFeedbackLogicValues, 'traceFeedback' | 'traceFeedbackFailed' | 'stepFeedback'> &
    Pick<traceSearchLogicValues, 'matchingNodeIds' | 'highlightQuery'> &
    Pick<traceClustersLogicValues, 'clusters'> &
    Pick<traceGitPullRequestLogicValues, 'pullRequest'> &
    Pick<
        traceReviewLogicValues,
        'reviewStatus' | 'reviewStatusFailed' | 'queueHref' | 'canEditReviews' | 'removeFromQueueLoading'
    > & {
        traceId: string
        traceExportLoading: boolean
        traceCopying: boolean
        backLink: LabeledLink | null
        messagesOpening: MessagesOpening
        datasetsEnabled: boolean
        summaryState: SummaryModeState
        summaryRequesting: boolean
        summaryRequestError: SummaryRequestError | null
        summaryConsentGiven: boolean
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
        tree: trace.tree,
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
        timeline: { rows: trace.timeline, totalMs: trace.totalMs },
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
        feedbackCount: values.traceFeedback?.summary.total ?? null,
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
        trace,
        mode,
        selectedNodeId,
        selectedTreeNode,
        selectedNodeLoad,
        detailTab,
        selectedRaw,
        canViewInThread,
        thread,
        searchBox,
        matchStepCount,
        feedbackFocusNodeId,
        selectedStepFeedback,
    } = useValues(logic)
    const actions = useActions(logic)
    const { status, loadFailure, evaluationResults, evaluationResultsFailed, createdAt, evalOutcomes, stepLabels } =
        useValues(traceViewLogic({ traceId, timestampHint }))
    const { traceFeedback, traceFeedbackFailed, stepFeedback } = useValues(
        traceFeedbackLogic({ traceId, timestampHint })
    )
    const { matchingNodeIds, highlightQuery } = useValues(traceSearchLogic({ traceId, timestampHint }))
    const { clusters } = useValues(traceClustersLogic({ traceId }))
    const { pullRequest } = useValues(traceGitPullRequestLogic({ traceId, timestampHint }))
    const summaryLogic = traceSummaryLogic({ traceId })
    const {
        state: summaryState,
        requesting: summaryRequesting,
        requestError: summaryRequestError,
        dataProcessingAccepted: summaryConsentGiven,
    } = useValues(summaryLogic)
    const { loadSummary } = useActions(summaryLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const datasetsEnabled = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_DATASETS]
    const exportLogic = traceExportLogic({ traceId, timestampHint })
    const { traceExportLoading, traceCopying } = useValues(exportLogic)
    const { exportTrace, copyTrace } = useActions(exportLogic)
    const reviewLogic = traceReviewLogic({ traceId })
    const { reviewStatus, reviewStatusFailed, queueHref, canEditReviews, removeFromQueueLoading } =
        useValues(reviewLogic)
    const { loadReviewStatus, removeFromQueue } = useActions(reviewLogic)
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
                      mode,
                      selectedNodeId,
                      selectedTreeNode,
                      selectedNodeLoad,
                      detailTab,
                      selectedRaw,
                      canViewInThread,
                      thread,
                      searchBox,
                      matchStepCount,
                      feedbackFocusNodeId,
                      selectedStepFeedback,
                      evaluationResults,
                      evaluationResultsFailed,
                      createdAt,
                      evalOutcomes,
                      stepLabels,
                      traceFeedback,
                      traceFeedbackFailed,
                      stepFeedback,
                      matchingNodeIds,
                      highlightQuery,
                      clusters,
                      pullRequest,
                      reviewStatus,
                      reviewStatusFailed,
                      queueHref,
                      canEditReviews,
                      removeFromQueueLoading,
                      traceId,
                      traceExportLoading,
                      traceCopying,
                      backLink,
                      messagesOpening,
                      datasetsEnabled,
                      summaryState,
                      summaryRequesting,
                      summaryRequestError,
                      summaryConsentGiven,
                  },
                  {
                      ...actions,
                      exportTrace,
                      copyTrace,
                      loadReviewStatus,
                      removeFromQueue,
                      setMessagesOpening,
                      loadSummary,
                  }
              )
            : null

    const props: TraceViewProps = readyProps
        ? { status: 'ready', ...readyProps }
        : status === 'error' && loadFailure
          ? { status: 'error', loadFailure, backLink }
          : { status: 'loading' }

    return <TraceView {...props} />
})
