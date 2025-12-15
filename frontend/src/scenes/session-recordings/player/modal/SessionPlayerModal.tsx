import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'

import { SessionRecordingPlayerLogicProps, sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { sessionPlayerModalLogic } from './sessionPlayerModalLogic'

/**
 * When SessionPlayerModal is present in the page you can call `openSessionPlayer` action to open the modal
 * and play a given session
 *
 * It assumes it is only placed in the page once and lives in the GlobalModals component as a result
 * Adding it to the page more than once will cause weird playback behaviour
 *
 */
export function SessionPlayerModal(): JSX.Element | null {
    const { activeSessionRecording } = useValues(sessionPlayerModalLogic())
    const { closeSessionPlayer } = useActions(sessionPlayerModalLogic())

    // activeSessionRecording?.matching_events should always be a single element array
    // but, we're filtering and using flatMap just in case
    const matchedEvents =
        activeSessionRecording?.matching_events
            ?.filter((matchingEvents) => {
                return matchingEvents.session_id === activeSessionRecording?.id
            })
            .flatMap((matchedRecording) => matchedRecording.events) || []

    const logicProps: SessionRecordingPlayerLogicProps = {
        playerKey: 'modal',
        sessionRecordingId: activeSessionRecording?.id || '',
        autoPlay: true,
        matchingEventsMatchType: {
            matchType: 'uuid',
            matchedEvents: matchedEvents,
        },
    }

    const { isFullScreen } = useValues(sessionRecordingPlayerLogic(logicProps))

    return (
        <LemonModal
            isOpen={!!activeSessionRecording}
            onClose={closeSessionPlayer}
            simple
            title=""
            width={1600}
            fullScreen={isFullScreen}
            closable={!isFullScreen}
            zIndex="1161"
            hideCloseButton={true}
        >
            <LemonModal.Content embedded>
                {activeSessionRecording?.id && <SessionRecordingPlayer {...logicProps} noBorder />}
            </LemonModal.Content>
        </LemonModal>
    )
}
