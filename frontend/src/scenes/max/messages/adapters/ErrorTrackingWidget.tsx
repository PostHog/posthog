import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { FallbackMcpToolRenderer } from '../FallbackMcpToolRenderer'
import { ErrorTrackingFiltersWidget } from '../UIPayloadAnswer'
import { extractErrorTrackingResponse } from './extractors'

/**
 * Error-tracking search / filter tool calls. `rawOutput` is a `MaxErrorTrackingSearchResponse`
 * directly; `ErrorTrackingFiltersWidget` renders the filter chips + paginated issue list (and
 * pushes filters into the error-tracking scene when it is active). Pre-completion or missing output
 * falls back to the generic card.
 */
export function ErrorTrackingWidget(props: McpToolRendererProps): JSX.Element {
    const { message } = props
    const filters = message.status === 'completed' ? extractErrorTrackingResponse(message) : null

    if (!filters) {
        return <FallbackMcpToolRenderer {...props} />
    }

    return <ErrorTrackingFiltersWidget toolCallId={message.id} filters={filters} />
}
