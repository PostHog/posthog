import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { FallbackMcpToolRenderer } from '../FallbackMcpToolRenderer'
import { ErrorTrackingFiltersWidget } from '../UIPayloadAnswer'
import { extractErrorTrackingResponse } from './extractors'

/**
 * Error-tracking search / filter tool calls. `rawOutput` is a `MaxErrorTrackingSearchResponse`
 * directly; `ErrorTrackingFiltersWidget` renders the filter chips + paginated issue list (and
 * pushes filters into the error-tracking scene when it is active). Pre-completion or missing output
 * falls back to the generic card. See docs/internal/posthog-ai-migration/03_RICH_UI.md § 4.2 and
 * MCP_TOOLS.md `search_error_tracking_issues`.
 */
export function ErrorTrackingAdapter({ message, isLastInGroup }: McpToolRendererProps): JSX.Element {
    const filters = message.status === 'completed' ? extractErrorTrackingResponse(message) : null

    if (!filters) {
        return <FallbackMcpToolRenderer message={message} isLastInGroup={isLastInGroup} />
    }

    return <ErrorTrackingFiltersWidget toolCallId={message.id} filters={filters} />
}
