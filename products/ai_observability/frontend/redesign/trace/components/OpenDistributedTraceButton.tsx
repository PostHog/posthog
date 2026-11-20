import type { MouseEvent } from 'react'

import { ViewTraceButton } from 'lib/components/ViewTraceButton/ViewTraceButton'

export interface OpenDistributedTraceButtonProps {
    traceId: string
    timestamp: string | null
    /** Opens the trace in place. When it does not prevent the default, the link navigates to Tracing. */
    onOpen: (event: MouseEvent) => void
}

export function OpenDistributedTraceButton({
    traceId,
    timestamp,
    onOpen,
}: OpenDistributedTraceButtonProps): JSX.Element | null {
    return (
        <ViewTraceButton
            traceId={traceId}
            timestamp={timestamp}
            label="Open distributed trace"
            type="secondary"
            size="small"
            data-attr="trace-view-open-distributed-trace"
            onClick={onOpen}
        />
    )
}
