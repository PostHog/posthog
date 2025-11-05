import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { SessionRecordingPreview } from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import {
    SessionRecordingPlaylistLogicProps,
    sessionRecordingsPlaylistLogic,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { AssistantTool } from '~/queries/schema/schema-assistant-messages'
import { RecordingUniversalFilters } from '~/types'

import { MessageTemplate } from './MessageTemplate'
import { RecordingsFiltersSummary } from './RecordingsFiltersSummary'

export const RENDERABLE_UI_PAYLOAD_TOOLS: AssistantTool[] = ['search_session_recordings']

export function UIPayloadAnswer({ toolName, toolPayload }: { toolName: string; toolPayload: any }): JSX.Element | null {
    if (toolName === 'search_session_recordings') {
        const filters = toolPayload as RecordingUniversalFilters
        return <RecordingsWidget filters={filters} />
    }
    // It's not expected to hit the null branch below, because such a case SHOULD have already been filtered out
    // in maxThreadLogic.selectors.threadGrouped, but better safe than sorry - there can be deployments mismatches etc.
    return null
}

function RecordingsWidget({ filters }: { filters: RecordingUniversalFilters }): JSX.Element {
    const logicProps: SessionRecordingPlaylistLogicProps = {
        logicKey: 'ai-recordings-widget',
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

    const hasRecordings = otherRecordings.length > 0

    return (
        <div className="border-t">
            {sessionRecordingsResponseLoading && !hasRecordings ? (
                <div className="flex items-center justify-center gap-2 py-12 text-muted">
                    <Spinner textColored />
                    <span>Loading recordings...</span>
                </div>
            ) : !hasRecordings ? (
                <div className="py-12 text-center">
                    <EmptyMessage title="No recordings found" description="No recordings match the specified filters" />
                </div>
            ) : (
                <>
                    <div className="divide-y">
                        {otherRecordings.map((recording) => (
                            <SessionRecordingPreview key={recording.id} recording={recording} selectable={false} />
                        ))}
                    </div>
                    {hasNext && (
                        <div className="border-t p-3">
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
