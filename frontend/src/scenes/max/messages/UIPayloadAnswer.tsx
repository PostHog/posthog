import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { SessionRecordingPreview } from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import {
    SessionRecordingPlaylistLogicProps,
    sessionRecordingsPlaylistLogic,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { AssistantTool } from '~/queries/schema/schema-assistant-messages'
import { RecordingUniversalFilters } from '~/types'

import { DangerousOperationApprovalCard } from '../DangerousOperationApprovalCard'
import { isDangerousOperationResponse, normalizeDangerousOperationResponse } from '../approvalOperationUtils'
import { maxLogic } from '../maxLogic'
import { MessageTemplate } from './MessageTemplate'
import { RecordingsFiltersSummary } from './RecordingsFiltersSummary'

export const RENDERABLE_UI_PAYLOAD_TOOLS: AssistantTool[] = [
    'search_session_recordings',
    'create_form',
    'upsert_dashboard',
]

export function UIPayloadAnswer({
    toolCallId,
    toolName,
    toolPayload,
}: {
    toolCallId: string
    toolName: string
    toolPayload: any
}): JSX.Element | null {
    const { conversationId } = useValues(maxLogic)

    if (toolName === 'search_session_recordings') {
        const filters = toolPayload as RecordingUniversalFilters
        return <RecordingsWidget toolCallId={toolCallId} filters={filters} />
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

export function RecordingsWidget({
    toolCallId,
    filters,
}: {
    toolCallId: string
    filters: RecordingUniversalFilters
}): JSX.Element {
    const logicProps: SessionRecordingPlaylistLogicProps = {
        logicKey: `ai-recordings-widget-${toolCallId}`,
        filters,
        updateSearchParams: false,
        autoPlay: false,
    }

    return (
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            <MessageTemplate type="ai" wrapperClassName="w-full" boxClassName="p-0 overflow-hidden">
                <RecordingsFiltersSummary filters={filters} />
                <RecordingsListContent />
            </MessageTemplate>
        </BindLogic>
    )
}

function RecordingsListContent(): JSX.Element {
    const { otherRecordings, sessionRecordingsResponseLoading, hasNext } = useValues(sessionRecordingsPlaylistLogic)
    const { maybeLoadSessionRecordings } = useActions(sessionRecordingsPlaylistLogic)
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic())

    const hasRecordings = otherRecordings.length > 0

    return (
        <div className="border-t *:not-first:border-t max-h-80 overflow-y-auto">
            {sessionRecordingsResponseLoading && !hasRecordings ? (
                <div className="flex items-center justify-center gap-2 py-12 text-muted">
                    <Spinner textColored />
                    <span>Loading recordings...</span>
                </div>
            ) : !hasRecordings ? (
                <div className="py-2">
                    <EmptyMessage title="No recordings found" description="No recordings match the specified filters" />
                </div>
            ) : (
                <>
                    {otherRecordings.map((recording) => (
                        <div
                            key={recording.id}
                            onClick={(e) => {
                                e.preventDefault()
                                openSessionPlayer(recording)
                            }}
                        >
                            <SessionRecordingPreview recording={recording} selectable={false} />
                        </div>
                    ))}
                    {hasNext && (
                        <div className="p-2">
                            <LemonButton
                                fullWidth
                                type="secondary"
                                size="small"
                                onClick={() => maybeLoadSessionRecordings('older')}
                                loading={sessionRecordingsResponseLoading}
                            >
                                Load more recordings
                            </LemonButton>
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
