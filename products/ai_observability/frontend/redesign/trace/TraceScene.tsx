import { useValues } from 'kea'

import { TRACE_PAGE_HOST_ID, tracePageLogic } from './tracePageLogic'
import { TraceViewHost } from './TraceViewHost'

export function TraceScene(): JSX.Element | null {
    const { traceId, timestampHint, backLink } = useValues(tracePageLogic)
    if (!traceId) {
        return null
    }
    return (
        <div className="flex min-h-0 flex-1 flex-col pb-4">
            <TraceViewHost
                hostId={TRACE_PAGE_HOST_ID}
                traceId={traceId}
                timestampHint={timestampHint}
                backLink={backLink}
            />
        </div>
    )
}
