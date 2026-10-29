import { useActions, useValues } from 'kea'

import { aiObservabilityTraceLogic } from '../../aiObservabilityTraceLogic'
import { SaveToDatasetButton } from '../../datasets/SaveToDatasetButton'
import { traceViewAdapterLogic, traceViewAdapterLogicValues } from './adapter/traceViewAdapterLogic'
import { TraceView, TraceViewProps, TraceViewReadyProps } from './components/TraceView'
import { MatchDirection, NodeDetailTab, SummaryItemKind, TraceMode } from './types'

type ReadyValues = Pick<
    traceViewAdapterLogicValues,
    | 'header'
    | 'summary'
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
>

interface ReadyActions {
    setMode: (mode: TraceMode) => void
    selectNode: (id: string) => void
    selectAndShowSpans: (id: string) => void
    setDetailTab: (tab: NodeDetailTab) => void
    viewInThread: () => void
    prefetchNode: (id: string) => void
    showFailingEvals: () => void
    setQuery: (query: string) => void
    stepMatch: (direction: MatchDirection) => void
    summarize: () => void
    regenerateSummary: () => void
    loadSummary: () => void
    summaryStepClicked: (nodeId: string, kind: SummaryItemKind) => void
}

function toReadyProps(values: ReadyValues, actions: ReadyActions): TraceViewReadyProps | null {
    if (!values.summary) {
        return null
    }
    return {
        header: values.header,
        summary: {
            ...values.summary,
            evals: values.evalsChip ? { chip: values.evalsChip, onClick: actions.showFailingEvals } : null,
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
    }
}

export function TraceScene(): JSX.Element {
    const { traceId, dateRange } = useValues(aiObservabilityTraceLogic)
    const logic = traceViewAdapterLogic({ traceId, timestampHint: dateRange?.dateFrom ?? null })
    // Every kea value getter is a hook, so read them all on every render, whatever the status.
    const {
        status,
        errorMessage,
        backLink,
        header,
        summary,
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
    } = useValues(logic)
    const actions = useActions(logic)

    const readyProps =
        status === 'ready'
            ? toReadyProps(
                  {
                      header,
                      summary,
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
                  },
                  actions
              )
            : null

    const props: TraceViewProps = readyProps
        ? { status: 'ready', ...readyProps }
        : status === 'error'
          ? { status: 'error', errorMessage, backLink }
          : { status: 'loading' }

    return <TraceView {...props} />
}
