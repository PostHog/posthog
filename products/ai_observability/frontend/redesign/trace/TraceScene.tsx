import { useActions, useValues } from 'kea'

import { aiObservabilityTraceLogic } from '../../aiObservabilityTraceLogic'
import { SaveToDatasetButton } from '../../datasets/SaveToDatasetButton'
import { traceViewAdapterLogic, traceViewAdapterLogicValues } from './adapter/traceViewAdapterLogic'
import { TraceView, TraceViewProps, TraceViewReadyProps } from './components/TraceView'
import { traceExportLogic } from './traceExportLogic'
import { FeedbackEntry, MatchDirection, NodeDetailTab, SummaryItemKind, TraceMode } from './types'

type ReadyValues = Pick<
    traceViewAdapterLogicValues,
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
> & { traceExportLoading: boolean }

interface ReadyActions {
    setMode: (mode: TraceMode) => void
    selectNode: (id: string) => void
    selectAndShowSpans: (id: string) => void
    setDetailTab: (tab: NodeDetailTab) => void
    viewInThread: () => void
    prefetchNode: (id: string) => void
    exportTrace: () => void
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

export function TraceScene(): JSX.Element {
    const { traceId, dateRange } = useValues(aiObservabilityTraceLogic)
    const logicProps = { traceId, timestampHint: dateRange?.dateFrom ?? null }
    const logic = traceViewAdapterLogic(logicProps)
    // Every kea value getter is a hook, so read them all on every render, whatever the status.
    const {
        status,
        errorMessage,
        backLink,
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
    const exportLogic = traceExportLogic(logicProps)
    const { traceExportLoading } = useValues(exportLogic)
    const { exportTrace } = useActions(exportLogic)

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
                  },
                  { ...actions, exportTrace }
              )
            : null

    const props: TraceViewProps = readyProps
        ? { status: 'ready', ...readyProps }
        : status === 'error'
          ? { status: 'error', errorMessage, backLink }
          : { status: 'loading' }

    return <TraceView {...props} />
}
