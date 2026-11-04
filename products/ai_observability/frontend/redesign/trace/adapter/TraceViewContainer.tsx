import { useActions, useValues } from 'kea'
import { memo } from 'react'

import { SaveToDatasetButton } from '../../../datasets/SaveToDatasetButton'
import { TraceView, TraceViewProps, TraceViewReadyProps } from '../components/TraceView'
import { traceExportLogic } from '../traceExportLogic'
import { traceViewModelLogic, traceViewModelLogicValues } from '../traceViewModelLogic'
import { FeedbackEntry, LabeledLink, MatchDirection, NodeDetailTab, SummaryItemKind, TraceMode } from '../types'

export interface TraceViewContainerProps {
    hostId: string
    traceId: string
    timestampHint: string | null
    backLink: LabeledLink | null
}

type ReadyValues = Pick<
    traceViewModelLogicValues,
    | 'header'
    | 'summary'
    | 'clustersChip'
    | 'mode'
    | 'tree'
    | 'selectedNodeId'
    | 'detailData'
    | 'detailTab'
    | 'datasetItemSource'
    | 'canViewInThread'
    | 'thread'
    | 'timeline'
    | 'evalsChip'
    | 'evalOutcomesByNode'
    | 'gitBranch'
    | 'searchBox'
    | 'matchingNodeIds'
    | 'highlightQuery'
    | 'matchStepCount'
    | 'summaryState'
    | 'summaryRequesting'
    | 'summaryRequestError'
    | 'summaryConsentGiven'
    | 'feedbackChip'
    | 'feedbackCount'
    | 'feedbackCountByNodeId'
    | 'feedbackMode'
    | 'selectedStepFeedback'
> & { traceExportLoading: boolean; traceCopying: boolean; backLink: LabeledLink | null }

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
}

function toReadyProps(values: ReadyValues, actions: ReadyActions): TraceViewReadyProps | null {
    if (!values.summary) {
        return null
    }
    return {
        header: {
            ...values.header,
            backLink: values.backLink,
            copyAction: { loading: values.traceCopying, onCopy: actions.copyTrace },
            exportAction: { loading: values.traceExportLoading, onExport: actions.exportTrace },
        },
        summary: {
            ...values.summary,
            clusters: values.clustersChip,
            evals: values.evalsChip ? { chip: values.evalsChip, onClick: actions.showFailingEvals } : null,
            feedback: values.feedbackChip
                ? { chip: values.feedbackChip, onClick: () => actions.showFeedback(null, 'chip') }
                : null,
            git: values.gitBranch,
        },
        mode: values.mode,
        onModeChange: actions.setMode,
        tree: values.tree,
        selectedNodeId: values.selectedNodeId,
        onSelectNode: actions.selectNode,
        onPrefetchNode: actions.prefetchNode,
        onSelectFromView: actions.selectAndShowSpans,
        detail: values.detailData
            ? {
                  ...values.detailData,
                  tab: values.detailTab,
                  onTabChange: actions.setDetailTab,
                  onViewInThread: values.canViewInThread ? actions.viewInThread : null,
                  actions: values.datasetItemSource ? <SaveToDatasetButton {...values.datasetItemSource} /> : null,
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
        evalOutcomes: values.evalOutcomesByNode,
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
        feedbackMode: values.feedbackMode,
        onRetryFeedback: actions.retryTraceFeedback,
        feedbackCount: values.feedbackCount,
        feedbackCountByNodeId: values.feedbackCountByNodeId,
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
        errorMessage,
        header,
        summary,
        clustersChip,
        mode,
        tree,
        selectedNodeId,
        detailData,
        detailTab,
        datasetItemSource,
        canViewInThread,
        thread,
        timeline,
        evalsChip,
        evalOutcomesByNode,
        gitBranch,
        searchBox,
        matchingNodeIds,
        highlightQuery,
        matchStepCount,
        summaryState,
        summaryRequesting,
        summaryRequestError,
        summaryConsentGiven,
        feedbackChip,
        feedbackCount,
        feedbackCountByNodeId,
        feedbackMode,
        selectedStepFeedback,
    } = useValues(logic)
    const actions = useActions(logic)
    const exportLogic = traceExportLogic({ traceId, timestampHint })
    const { traceExportLoading, traceCopying } = useValues(exportLogic)
    const { exportTrace, copyTrace } = useActions(exportLogic)

    const readyProps =
        status === 'ready'
            ? toReadyProps(
                  {
                      header,
                      summary,
                      clustersChip,
                      mode,
                      tree,
                      selectedNodeId,
                      detailData,
                      detailTab,
                      datasetItemSource,
                      canViewInThread,
                      thread,
                      timeline,
                      evalsChip,
                      evalOutcomesByNode,
                      gitBranch,
                      searchBox,
                      matchingNodeIds,
                      highlightQuery,
                      matchStepCount,
                      summaryState,
                      summaryRequesting,
                      summaryRequestError,
                      summaryConsentGiven,
                      feedbackChip,
                      feedbackCount,
                      feedbackCountByNodeId,
                      feedbackMode,
                      selectedStepFeedback,
                      traceExportLoading,
                      traceCopying,
                      backLink,
                  },
                  { ...actions, exportTrace, copyTrace }
              )
            : null

    const props: TraceViewProps = readyProps
        ? { status: 'ready', ...readyProps }
        : status === 'error'
          ? { status: 'error', errorMessage, backLink }
          : { status: 'loading' }

    return <TraceView {...props} />
})
