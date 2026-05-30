import { useMemo } from 'react'

import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { MessageTemplate } from '../MessageTemplate'
import { SessionSummarizationProgress } from '../SessionSummarizationProgress'
import { SummarizeSessionsWidget } from '../UIPayloadAnswer'
import { extractSummarizePayload, parseSessionSummarizationUpdates } from './extractors'

/**
 * Renders `session-recording-summarize`. The adapter accumulates the streamed
 * `SessionSummarizationUpdate` JSON frames from `content[]` (so `SessionSummarizationProgress`
 * stays unchanged) and shows the `SummarizeSessionsWidget` CTA once `rawOutput` carries the
 * finished `session_group_summary_id`.
 * See docs/internal/posthog-ai-migration/03_RICH_UI.md §3.3 Example C.
 */
export function SummarizeSessionsAdapter({ message }: McpToolRendererProps): JSX.Element {
    const updates = useMemo(() => parseSessionSummarizationUpdates(message.content), [message.content])
    const payload = extractSummarizePayload(message)

    return (
        <MessageTemplate type="ai">
            <SessionSummarizationProgress updates={updates} />
            {payload?.session_group_summary_id && <SummarizeSessionsWidget payload={payload} title={payload.title} />}
        </MessageTemplate>
    )
}
