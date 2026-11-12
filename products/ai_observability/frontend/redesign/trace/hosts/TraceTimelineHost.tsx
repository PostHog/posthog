import { useActions, useValues } from 'kea'

import { TraceTimeline } from '../components/TraceTimeline'
import { traceSearchLogic } from '../traceSearchLogic'
import { traceViewLogic } from '../traceViewLogic'
import { traceViewModelLogic } from '../traceViewModelLogic'
import { TraceViewKey } from '../types'

export function TraceTimelineHost({ hostId, traceId, timestampHint }: TraceViewKey): JSX.Element | null {
    const { trace } = useValues(traceViewLogic({ traceId, timestampHint }))
    const viewModel = traceViewModelLogic({ hostId, traceId, timestampHint })
    const { selectedNodeId } = useValues(viewModel)
    const { selectAndShowSpans, prefetchNode } = useActions(viewModel)
    const { matchingNodeIds } = useValues(traceSearchLogic({ traceId, timestampHint }))
    if (!trace) {
        return null
    }
    return (
        <TraceTimeline
            rows={trace.timeline}
            totalMs={trace.totalMs}
            selectedNodeId={selectedNodeId}
            onSelectNode={selectAndShowSpans}
            onPrefetchNode={prefetchNode}
            matchingNodeIds={matchingNodeIds}
        />
    )
}
