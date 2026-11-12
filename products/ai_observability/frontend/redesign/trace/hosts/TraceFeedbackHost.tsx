import { useActions, useValues } from 'kea'

import { TraceFeedbackView } from '../components/TraceFeedbackView'
import { traceFeedbackLogic } from '../traceFeedbackLogic'
import { traceViewLogic } from '../traceViewLogic'
import { traceViewModelLogic } from '../traceViewModelLogic'
import { TraceViewKey } from '../types'

export function TraceFeedbackHost({ hostId, traceId, timestampHint }: TraceViewKey): JSX.Element {
    const feedbackLogic = traceFeedbackLogic({ traceId, timestampHint })
    const { traceFeedback, traceFeedbackFailed } = useValues(feedbackLogic)
    const { retryTraceFeedback } = useActions(feedbackLogic)
    const { stepLabels } = useValues(traceViewLogic({ traceId, timestampHint }))
    const viewModel = traceViewModelLogic({ hostId, traceId, timestampHint })
    const { feedbackFocusNodeId } = useValues(viewModel)
    const { selectAndShowSpans } = useActions(viewModel)
    return (
        <TraceFeedbackView
            feedback={traceFeedback}
            failed={traceFeedbackFailed}
            steps={{ traceId, stepLabels, focusNodeId: feedbackFocusNodeId }}
            onSelectStep={selectAndShowSpans}
            onRetry={retryTraceFeedback}
        />
    )
}
