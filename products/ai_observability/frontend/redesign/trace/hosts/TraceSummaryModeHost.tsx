import { useActions, useValues } from 'kea'

import { SummaryModeView } from '../components/SummaryModeView'
import { traceSummaryLogic } from '../traceSummaryLogic'
import { traceViewModelLogic } from '../traceViewModelLogic'
import { TraceViewKey } from '../types'

export function TraceSummaryModeHost({ hostId, traceId, timestampHint }: TraceViewKey): JSX.Element {
    const summaryLogic = traceSummaryLogic({ traceId })
    const { state, requesting, requestError, dataProcessingAccepted } = useValues(summaryLogic)
    const { loadSummary } = useActions(summaryLogic)
    const { summarize, regenerateSummary, summaryStepClicked } = useActions(
        traceViewModelLogic({ hostId, traceId, timestampHint })
    )
    return (
        <SummaryModeView
            state={state}
            requesting={requesting}
            requestError={requestError}
            consentGiven={dataProcessingAccepted}
            onRequest={summarize}
            onRegenerate={regenerateSummary}
            onReload={loadSummary}
            onSelectStep={summaryStepClicked}
        />
    )
}
