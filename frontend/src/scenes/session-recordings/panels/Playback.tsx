import { useValues } from 'kea'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'

import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { sessionRecordingsPlaylistLogic } from '../playlist/sessionRecordingsPlaylistLogic'

export const PanelPlayback = ({ logicKey }: { logicKey?: string }): JSX.Element => {
    const { pinnedRecordings, matchingEventsMatchType, activeSessionRecordingId } =
        useValues(sessionRecordingsPlaylistLogic)

    return activeSessionRecordingId ? (
        <SessionRecordingPlayer
            playerKey={logicKey ?? 'playlist'}
            sessionRecordingId={activeSessionRecordingId}
            matchingEventsMatchType={matchingEventsMatchType}
            playlistLogic={sessionRecordingsPlaylistLogic}
            noBorder
            noInspector
            pinned={!!pinnedRecordings.find((x) => x.id === activeSessionRecordingId)}
            // TODO: re-add this
            // setPinned={
            //     props.onPinnedChange
            //         ? (pinned) => {
            //               if (!activeItem.id) {
            //                   return
            //               }
            //               props.onPinnedChange?.(activeItem, pinned)
            //           }
            //         : undefined
            // }
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
