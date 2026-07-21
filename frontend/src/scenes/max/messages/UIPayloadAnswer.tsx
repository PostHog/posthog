import { useValues } from 'kea'

import { IconNotebook } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { MaxErrorTrackingSearchResponse } from '~/queries/schema/schema-assistant-error-tracking'
import { AssistantTool } from '~/queries/schema/schema-assistant-messages'
import { RecordingUniversalFilters } from '~/types'

import {
    ErrorTrackingFiltersWidget,
    MessageTemplate,
    RecordingsWidget,
} from 'products/posthog_ai/frontend/api/primitives'

import { isDangerousOperationResponse, normalizeDangerousOperationResponse } from '../approvalOperationUtils'
import { DangerousOperationApprovalCard } from '../DangerousOperationApprovalCard'
import { maxLogic } from '../maxLogic'
import { AnnotatedScreenshotView, parseAnnotatedScreenshot } from './AnnotatedScreenshotView'

export const RENDERABLE_UI_PAYLOAD_TOOLS: AssistantTool[] = [
    'search_session_recordings',
    'search_error_tracking_issues',
    'summarize_sessions',
    'create_form',
]

export function isRenderableUIPayloadTool(toolName: string, toolPayload: unknown): boolean {
    return (
        (RENDERABLE_UI_PAYLOAD_TOOLS as readonly string[]).includes(toolName) ||
        isDangerousOperationResponse(toolPayload)
    )
}

// Renders rich UI for a small set of tools that return structured payloads (recordings search,
// error-tracking search, create_form, upsert_dashboard) and for dangerous-operation approval cards.
export function UIPayloadAnswer({
    toolCallId,
    toolName,
    toolPayload,
    embedded = false,
}: {
    toolCallId: string
    toolName: string
    toolPayload: any
    embedded?: boolean
}): JSX.Element | null {
    const { conversationId, onAcceptSessionFilters } = useValues(maxLogic)

    if (toolName === 'search_session_recordings') {
        const filters = toolPayload as RecordingUniversalFilters
        return (
            <RecordingsWidget
                toolCallId={toolCallId}
                filters={filters}
                embedded={embedded}
                onAcceptFilters={onAcceptSessionFilters}
            />
        )
    }
    if (toolName === 'search_error_tracking_issues') {
        const filters = toolPayload as MaxErrorTrackingSearchResponse
        return <ErrorTrackingFiltersWidget toolCallId={toolCallId} filters={filters} embedded={embedded} />
    }
    if (toolName === 'summarize_website_interactions') {
        const data = parseAnnotatedScreenshot((toolPayload as { screenshot?: unknown } | null)?.screenshot)
        if (!data) {
            return null
        }
        return embedded ? (
            <div className="overflow-hidden rounded border bg-surface-primary p-2">
                <AnnotatedScreenshotView data={data} />
            </div>
        ) : (
            <MessageTemplate type="ai" wrapperClassName="w-full">
                <AnnotatedScreenshotView data={data} />
            </MessageTemplate>
        )
    }

    // Check if this is a dangerous operation requiring approval
    if (isDangerousOperationResponse(toolPayload)) {
        if (!conversationId) {
            return null
        }
        const normalizedOperation = normalizeDangerousOperationResponse(toolPayload)
        return <DangerousOperationApprovalCard operation={normalizedOperation} />
    }

    // It's not expected to hit the null branch below, because such a case SHOULD have already been filtered out
    // in maxThreadLogic.selectors.threadGrouped, but better safe than sorry - there can be deployments mismatches etc.
    return null
}

export function SummarizeSessionsWidget({
    payload,
    title,
}: {
    payload: { title?: string; session_group_summary_id?: string } | null | undefined
    title?: string
}): JSX.Element | null {
    if (!payload?.session_group_summary_id) {
        return null
    }

    return (
        <LemonButton
            to={urls.sessionSummary(payload.session_group_summary_id)}
            icon={<IconNotebook />}
            size="small"
            targetBlank
            type="primary"
            className="bg-surface-primary w-fit mx-1"
        >
            Open analysis of sessions{title && `: ${title}`}
        </LemonButton>
    )
}
