import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { FallbackMcpToolRenderer } from '../FallbackMcpToolRenderer'
import { RecordingsWidget } from '../UIPayloadAnswer'
import { extractRecordingFilters } from './extractors'

/**
 * Session-recording search / filter tool calls. The resolved `RecordingUniversalFilters` come back
 * in `rawOutput.filters`; `RecordingsWidget` renders the live playlist inline. Pre-completion or a
 * missing filter object falls back to the generic card.
 */
export function SearchSessionRecordingsWidget({ message, isLastInGroup }: McpToolRendererProps): JSX.Element {
    const filters = message.status === 'completed' ? extractRecordingFilters(message) : null

    if (!filters) {
        return <FallbackMcpToolRenderer message={message} isLastInGroup={isLastInGroup} />
    }

    return <RecordingsWidget toolCallId={message.id} filters={filters} />
}
