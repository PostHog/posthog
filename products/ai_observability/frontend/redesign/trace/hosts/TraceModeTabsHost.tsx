import { useActions, useValues } from 'kea'

import { TraceModeTabs } from '../components/TraceModeTabs'
import { traceFeedbackLogic } from '../traceFeedbackLogic'
import { traceViewHostLogic } from '../traceViewHostLogic'
import { traceViewModelLogic } from '../traceViewModelLogic'
import { TraceViewKey } from '../types'

export function TraceModeTabsHost({ hostId, traceId, timestampHint }: TraceViewKey): JSX.Element {
    const { mode } = useValues(traceViewHostLogic({ hostId }))
    const { setMode } = useActions(traceViewModelLogic({ hostId, traceId, timestampHint }))
    const { traceFeedback } = useValues(traceFeedbackLogic({ traceId, timestampHint }))
    return <TraceModeTabs mode={mode} onModeChange={setMode} feedbackCount={traceFeedback?.summary.total ?? null} />
}
