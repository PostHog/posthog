import { useValues } from 'kea'

import { TraceViewContainer } from './adapter/TraceViewContainer'
import { TRACE_PAGE_HOST_ID, tracePageLogic } from './tracePageLogic'

export function TraceScene(): JSX.Element | null {
    const { traceId, timestampHint, backLink } = useValues(tracePageLogic)
    if (!traceId) {
        return null
    }
    return (
        <div className="flex min-h-0 flex-1 flex-col pb-4">
            <TraceViewContainer
                hostId={TRACE_PAGE_HOST_ID}
                traceId={traceId}
                timestampHint={timestampHint}
                backLink={backLink}
            />
        </div>
    )
}
