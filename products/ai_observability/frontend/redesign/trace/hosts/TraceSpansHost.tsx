import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SaveToDatasetButton } from '../../../datasets/SaveToDatasetButton'
import { TraceSplitView } from '../components/TraceSplitView'
import { traceFeedbackLogic } from '../traceFeedbackLogic'
import { traceMessagesOpeningLogic } from '../traceMessagesOpeningLogic'
import { traceSearchLogic } from '../traceSearchLogic'
import { traceViewLogic } from '../traceViewLogic'
import { traceViewModelLogic } from '../traceViewModelLogic'
import { TraceViewKey } from '../types'

export function TraceSpansHost({ hostId, traceId, timestampHint }: TraceViewKey): JSX.Element | null {
    const { trace, evaluationResults, evaluationResultsFailed, evalOutcomes, stepLabels, createdAt } = useValues(
        traceViewLogic({ traceId, timestampHint })
    )
    const viewModel = traceViewModelLogic({ hostId, traceId, timestampHint })
    const {
        selectedNodeId,
        selectedTreeNode,
        selectedNodeLoad,
        selectedRaw,
        detailTab,
        canViewInThread,
        selectedStepFeedback,
        matchStepCount,
    } = useValues(viewModel)
    const { selectNode, prefetchNode, setDetailTab, viewInThread, showFeedback } = useActions(viewModel)
    const { stepFeedback } = useValues(traceFeedbackLogic({ traceId, timestampHint }))
    const { matchingNodeIds, highlightQuery } = useValues(traceSearchLogic({ traceId, timestampHint }))
    const { messagesOpening } = useValues(traceMessagesOpeningLogic)
    const { setMessagesOpening } = useActions(traceMessagesOpeningLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!trace) {
        return null
    }
    const datasetsEnabled = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_DATASETS]
    return (
        <TraceSplitView
            tree={trace.tree}
            selectedNodeId={selectedNodeId}
            onSelectNode={selectNode}
            onPrefetchNode={prefetchNode}
            evalOutcomes={evalOutcomes}
            stepFeedback={stepFeedback}
            matchingNodeIds={matchingNodeIds}
            highlightQuery={highlightQuery}
            matchStepCount={matchStepCount}
            detail={
                selectedTreeNode
                    ? {
                          node: selectedTreeNode,
                          load: selectedNodeLoad,
                          trace,
                          evaluationResults: evaluationResults?.results ?? null,
                          evaluationResultsFailed,
                          stepLabels,
                          raw: selectedRaw,
                          tab: detailTab,
                          onTabChange: setDetailTab,
                          onViewInThread: canViewInThread ? viewInThread : null,
                          messagesOpening,
                          onMessagesOpeningChange: setMessagesOpening,
                          actions:
                              datasetsEnabled && createdAt ? (
                                  <SaveToDatasetButton
                                      key={selectedNodeId}
                                      step={{ traceId, nodeId: selectedNodeId, timestamp: createdAt }}
                                  />
                              ) : null,
                          stepFeedback: selectedStepFeedback
                              ? {
                                    feedback: selectedStepFeedback,
                                    onOpen: () => showFeedback(selectedNodeId, 'step'),
                                }
                              : null,
                      }
                    : null
            }
        />
    )
}
