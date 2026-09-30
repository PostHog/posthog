import { useActions, useValues } from 'kea'

import { aiObservabilityTraceLogic } from '../../aiObservabilityTraceLogic'
import { traceViewAdapterLogic, traceViewAdapterLogicValues } from './adapter/traceViewAdapterLogic'
import { TraceView, TraceViewProps, TraceViewReadyProps } from './components/TraceView'
import { NodeDetailTab, TraceMode } from './types'

type ReadyValues = Pick<
    traceViewAdapterLogicValues,
    | 'header'
    | 'summary'
    | 'mode'
    | 'tree'
    | 'selectedNodeId'
    | 'detailData'
    | 'detailTab'
    | 'canViewInThread'
    | 'thread'
    | 'timeline'
>

interface ReadyActions {
    setMode: (mode: TraceMode) => void
    selectNode: (id: string) => void
    selectAndShowSpans: (id: string) => void
    setDetailTab: (tab: NodeDetailTab) => void
    viewInThread: () => void
}

function toReadyProps(values: ReadyValues, actions: ReadyActions): TraceViewReadyProps | null {
    if (!values.header || !values.summary) {
        return null
    }
    return {
        header: values.header,
        summary: values.summary,
        mode: values.mode,
        onModeChange: actions.setMode,
        tree: values.tree,
        selectedNodeId: values.selectedNodeId,
        onSelectNode: actions.selectNode,
        onSelectFromView: actions.selectAndShowSpans,
        detail: values.detailData
            ? {
                  ...values.detailData,
                  tab: values.detailTab,
                  onTabChange: actions.setDetailTab,
                  onViewInThread: values.canViewInThread ? actions.viewInThread : null,
              }
            : null,
        thread: values.thread,
        timeline: values.timeline,
    }
}

export function TraceScene(): JSX.Element {
    const { traceId, query } = useValues(aiObservabilityTraceLogic)
    const logic = traceViewAdapterLogic({ traceId, query })
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
        canViewInThread,
        thread,
        timeline,
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
                      canViewInThread,
                      thread,
                      timeline,
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
