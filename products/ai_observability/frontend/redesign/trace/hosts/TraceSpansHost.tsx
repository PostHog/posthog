import { useActions, useValues } from 'kea'

import { useShortcut } from 'lib/components/Shortcuts/useShortcut'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SaveToDatasetButton } from '../../../datasets/SaveToDatasetButton'
import { TraceSplitView } from '../components/TraceSplitView'
import { isOverlayOpen } from '../shouldCloseOnEscape'
import { traceFeedbackLogic } from '../traceFeedbackLogic'
import { traceMessagesOpeningLogic } from '../traceMessagesOpeningLogic'
import { traceSearchLogic } from '../traceSearchLogic'
import { traceViewHostLogic } from '../traceViewHostLogic'
import { traceViewLogic } from '../traceViewLogic'
import { traceViewModelLogic } from '../traceViewModelLogic'
import { StepDirection, TraceViewKey } from '../types'

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
        treeRevealCount,
    } = useValues(viewModel)
    const { selectNode, stepNode, prefetchNode, setDetailTab, viewInThread, showFeedback } = useActions(viewModel)
    const { stepFeedback } = useValues(traceFeedbackLogic({ traceId, timestampHint }))
    const { matchingNodeIds, highlightQuery } = useValues(traceSearchLogic({ traceId, timestampHint }))
    const { messagesOpening } = useValues(traceMessagesOpeningLogic)
    const { setMessagesOpening } = useActions(traceMessagesOpeningLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { canStepTraces } = useValues(traceViewHostLogic({ hostId }))

    // A dropdown or modal opened from the step belongs to that step, so a key never moves the selection under one.
    const stepUnlessOverlayOpen = (direction: StepDirection): void => {
        if (!isOverlayOpen()) {
            stepNode(direction, 'shortcut')
        }
    }
    useShortcut({
        name: 'TraceViewPreviousStep',
        keybind: [['k']],
        intent: 'Previous step',
        interaction: 'function',
        callback: () => stepUnlessOverlayOpen('previous'),
        disabled: !trace,
    })
    useShortcut({
        name: 'TraceViewNextStep',
        keybind: [['j']],
        intent: 'Next step',
        interaction: 'function',
        callback: () => stepUnlessOverlayOpen('next'),
        disabled: !trace,
    })

    if (!trace) {
        return null
    }
    const datasetsEnabled = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_DATASETS]
    return (
        <TraceSplitView
            tree={trace.tree}
            selectedNodeId={selectedNodeId}
            onSelectNode={selectNode}
            onStepNode={(step) => stepNode(step, 'arrow')}
            onPrefetchNode={prefetchNode}
            evalOutcomes={evalOutcomes}
            stepFeedback={stepFeedback}
            matchingNodeIds={matchingNodeIds}
            highlightQuery={highlightQuery}
            matchStepCount={matchStepCount}
            treeRevealCount={treeRevealCount}
            showTraceKeys={canStepTraces}
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
