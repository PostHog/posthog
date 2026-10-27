import { useActions, useValues } from 'kea'

import { aiObservabilityTraceLogic } from '../../aiObservabilityTraceLogic'
import { SaveToDatasetButton } from '../../datasets/SaveToDatasetButton'
import { traceViewAdapterLogic, traceViewAdapterLogicValues } from './adapter/traceViewAdapterLogic'
import { TraceView, TraceViewProps, TraceViewReadyProps } from './components/TraceView'
import { FeedbackEntry, NodeDetailTab, TraceMode } from './types'

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
    | 'feedbackChip'
    | 'feedbackCount'
    | 'feedbackCountByNodeId'
    | 'feedbackMode'
    | 'selectedStepFeedback'
>

interface ReadyActions {
    setMode: (mode: TraceMode) => void
    selectNode: (id: string) => void
    selectAndShowSpans: (id: string) => void
    setDetailTab: (tab: NodeDetailTab) => void
    viewInThread: () => void
    prefetchNode: (id: string) => void
    showFeedback: (nodeId: string | null, entry: FeedbackEntry) => void
    retryTraceFeedback: () => void
}

function toReadyProps(values: ReadyValues, actions: ReadyActions): TraceViewReadyProps | null {
    if (!values.summary) {
        return null
    }
    return {
        header: values.header,
        summary: {
            ...values.summary,
            feedback: values.feedbackChip
                ? { chip: values.feedbackChip, onClick: () => actions.showFeedback(null, 'chip') }
                : null,
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
        feedbackMode: values.feedbackMode,
        onRetryFeedback: actions.retryTraceFeedback,
        feedbackCount: values.feedbackCount,
        feedbackCountByNodeId: values.feedbackCountByNodeId,
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
        feedbackChip,
        feedbackCount,
        feedbackCountByNodeId,
        feedbackMode,
        selectedStepFeedback,
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
                      feedbackChip,
                      feedbackCount,
                      feedbackCountByNodeId,
                      feedbackMode,
                      selectedStepFeedback,
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
