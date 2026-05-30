import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { RecordingsWidget } from '../UIPayloadAnswer'
import { extractRecordingFilters } from './extractors'
import { FallbackMcpToolRenderer } from './FallbackMcpToolRenderer'

/**
 * Renders `query-session-recordings-list` via the existing `RecordingsWidget`. The tool input is a
 * flat `AssistantRecordingsQuery` (no `filter_group`/`duration`), which `extractRecordingFilters`
 * folds into a fully-typed `RecordingUniversalFilters` the widget can consume; the widget renders
 * the matching recordings inline.
 * See docs/internal/posthog-ai-migration/03_RICH_UI.md §4.
 */
export function SearchSessionRecordingsAdapter(props: McpToolRendererProps): JSX.Element {
    const filters = extractRecordingFilters(props.message)
    if (!filters) {
        return <FallbackMcpToolRenderer {...props} />
    }
    return <RecordingsWidget toolCallId={props.message.toolCallId} filters={filters} />
}
