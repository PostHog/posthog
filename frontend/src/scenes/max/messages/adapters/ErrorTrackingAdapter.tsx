import {
    MaxErrorTrackingIssuePreview,
    MaxErrorTrackingSearchResponse,
} from '~/queries/schema/schema-assistant-error-tracking'

import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { ErrorTrackingIssueCard } from '../ErrorTrackingIssueCard'
import { MessageTemplate } from '../MessageTemplate'
import { ErrorTrackingFiltersWidget } from '../UIPayloadAnswer'
import { asObject } from './extractors'
import { FallbackMcpToolRenderer } from './FallbackMcpToolRenderer'

/** Inner tools whose output is a single issue rather than a filtered list. */
const ISSUE_DETAIL_TOOLS = new Set(['query-error-tracking-issue', 'query-error-tracking-issue-events'])

function asIssuePreview(value: Record<string, unknown> | null): MaxErrorTrackingIssuePreview | null {
    if (!value || typeof value.id !== 'string') {
        return null
    }
    return value as unknown as MaxErrorTrackingIssuePreview
}

/**
 * Renders the error-tracking tools. `query-error-tracking-issues-list` reuses the existing
 * `ErrorTrackingFiltersWidget` (input/output is a `MaxErrorTrackingSearchResponse`). The
 * issue-detail variants (`query-error-tracking-issue` / `-issue-events`) render a single
 * `ErrorTrackingIssueCard`. Falls through to the generic card when the shape is unexpected.
 * See docs/internal/posthog-ai-migration/03_RICH_UI.md §4.
 */
export function ErrorTrackingAdapter(props: McpToolRendererProps): JSX.Element {
    const { message } = props
    const out = asObject(message.rawOutput)
    const innerTool = message.innerToolName ?? message.resolvedKey

    if (ISSUE_DETAIL_TOOLS.has(innerTool)) {
        const issue = asIssuePreview(out && (asObject(out.issue) ?? out))
        if (!issue) {
            return <FallbackMcpToolRenderer {...props} />
        }
        return (
            <MessageTemplate type="ai" wrapperClassName="w-full" boxClassName="p-0 overflow-hidden">
                <ErrorTrackingIssueCard issue={issue} />
            </MessageTemplate>
        )
    }

    return (
        <ErrorTrackingFiltersWidget
            toolCallId={message.toolCallId}
            filters={(out as MaxErrorTrackingSearchResponse | null) ?? undefined}
        />
    )
}
