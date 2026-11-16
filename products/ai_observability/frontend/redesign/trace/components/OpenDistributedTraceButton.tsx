import { usableId } from 'lib/components/ViewTraceButton/usableId'
import { ViewTraceButton } from 'lib/components/ViewTraceButton/ViewTraceButton'

import { useOpenTraceDialog } from 'products/tracing/frontend/components/TraceDialog/useOpenTraceDialog'

import type { TraceNodeDetailApi } from '../../../generated/api.schemas'

export interface OpenDistributedTraceButtonProps {
    traceId: string
    /** The selected step's event, once it has loaded. */
    event: TraceNodeDetailApi['event']
    /** Bounds the trace lookup while the step's event loads. */
    fallbackTimestamp: string | null | undefined
}

export function OpenDistributedTraceButton({
    traceId,
    event,
    fallbackTimestamp,
}: OpenDistributedTraceButtonProps): JSX.Element | null {
    const openTraceDialog = useOpenTraceDialog()
    const distributedTraceId = usableId(traceId)
    if (!distributedTraceId) {
        return null
    }
    const timestamp = event?.timestamp ?? fallbackTimestamp

    return (
        <ViewTraceButton
            traceId={distributedTraceId}
            // Tracing shows each AI event as a span with the id `ai:<event uuid>`.
            spanId={event ? `ai:${event.uuid}` : null}
            timestamp={timestamp}
            label="Open distributed trace"
            type="secondary"
            size="xsmall"
            data-attr="trace-view-open-in-tracing"
            onClick={(clickEvent) =>
                // The dialog loads no AI events, so it has no row to select for this step.
                openTraceDialog(
                    clickEvent,
                    { traceId: distributedTraceId, ts: timestamp },
                    { entryPoint: 'ai_trace_step' }
                )
            }
        />
    )
}
