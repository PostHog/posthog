import { useValues } from 'kea'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'

import { SessionRecordingType } from '~/types'

import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { sessionRecordingsPlaylistLogic } from '../playlist/sessionRecordingsPlaylistLogic'

export const PanelPlayback = ({
    logicKey,
    onPinnedChange,
}: {
    logicKey?: string
    onPinnedChange?: (recording: SessionRecordingType, pinned: boolean) => void
}): JSX.Element => {
    const { pinnedRecordings, matchingEventsMatchType, activeSessionRecordingId, activeSessionRecording } = useValues(
        sessionRecordingsPlaylistLogic({ updateSearchParams: true })
    )

    return activeSessionRecordingId ? (
        <SessionRecordingPlayer
            playerKey={logicKey ?? 'playlist'}
            sessionRecordingId={activeSessionRecordingId}
            matchingEventsMatchType={matchingEventsMatchType}
            playlistLogic={sessionRecordingsPlaylistLogic({ updateSearchParams: true })}
            noBorder
            noInspector
            pinned={!!pinnedRecordings.find((x) => x.id === activeSessionRecordingId)}
            setPinned={
                onPinnedChange
                    ? (pinned) => {
                          if (!activeSessionRecording) {
                              return
                          }
                          onPinnedChange?.(activeSessionRecording, pinned)
                      }
                    : undefined
            }
        />
    ) : (
        <div className="mt-20">
            <EmptyMessage
                title="No recording selected"
                description="Please select a recording from the list on the left"
                buttonText="Learn more about recordings"
                buttonTo="https://posthog.com/docs/user-guides/recordings"
            />
        </div>
    )
}
