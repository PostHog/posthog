import { useActions, useValues } from 'kea'

import { Thread } from '../components/Thread'
import { traceSearchLogic } from '../traceSearchLogic'
import { traceViewModelLogic } from '../traceViewModelLogic'
import { TraceViewKey } from '../types'

export function TraceThreadHost({ hostId, traceId, timestampHint }: TraceViewKey): JSX.Element {
    const viewModel = traceViewModelLogic({ hostId, traceId, timestampHint })
    const { thread } = useValues(viewModel)
    const { selectAndShowSpans } = useActions(viewModel)
    const { matchingNodeIds, highlightQuery } = useValues(traceSearchLogic({ traceId, timestampHint }))
    return (
        <Thread
            conversation={thread}
            onSelectMessage={selectAndShowSpans}
            highlightQuery={highlightQuery}
            matchingNodeIds={matchingNodeIds}
        />
    )
}
