import { GenericMcpToolRenderer } from '../../sandbox/components/tool/GenericMcpToolRenderer'
import { SandboxDataToolRow } from '../../sandbox/components/tool/SandboxDataToolRow'
import type { SandboxToolRendererProps } from '../../sandbox/sandboxToolRegistry'
import { RecordingsWidget } from '../UIPayloadAnswer'
import { extractRecordingFilters } from './extractors'

/**
 * Session-recording search / filter tool calls. The resolved `RecordingUniversalFilters` come back
 * in `rawOutput.filters`; `RecordingsWidget` renders the live playlist inline. Pre-completion or a
 * missing filter object falls back to the generic card.
 */
export function SearchSessionRecordingsWidget(props: SandboxToolRendererProps): JSX.Element {
    const { message } = props
    const filters = message.status === 'completed' ? extractRecordingFilters(message) : null

    if (!filters) {
        return <GenericMcpToolRenderer {...props} />
    }

    return (
        <SandboxDataToolRow {...props}>
            <RecordingsWidget toolCallId={message.id} filters={filters} embedded />
        </SandboxDataToolRow>
    )
}
