import { GenericMcpToolRenderer, DataToolRow, type ToolRendererProps } from 'products/posthog_ai/frontend/api/tools'

import { RecordingsWidget } from '../UIPayloadAnswer'
import { extractRecordingFilters } from './extractors'

/**
 * Session-recording search / filter tool calls. The resolved `RecordingUniversalFilters` come back
 * in `rawOutput.filters`; `RecordingsWidget` renders the live playlist inline. Pre-completion or a
 * missing filter object falls back to the generic card.
 */
export function SearchSessionRecordingsWidget(props: ToolRendererProps): JSX.Element {
    const { message } = props
    const filters = message.status === 'completed' ? extractRecordingFilters(message) : null

    if (!filters) {
        return <GenericMcpToolRenderer {...props} />
    }

    return (
        <DataToolRow {...props}>
            <RecordingsWidget toolCallId={message.id} filters={filters} embedded />
        </DataToolRow>
    )
}
