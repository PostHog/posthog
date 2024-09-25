import { LemonModal } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'

import { PlayerMeta } from '../PlayerMeta'
import { sessionRecordingPlayerLogic, SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'
import { sessionPlayerModalLogic } from './sessionPlayerModalLogic'

let sessionPlayerModalSingletonRendered = false

/**
 * When SessionPlayerModal is present in the page you can call `openSessionPlayer` action to open the modal
 * and play a given session
 *
 * SessionPlayerModal is templated into the page by multiple components
 * It has to be present _once_ for the player modal to work
 * But gets very unhappy if there are multiple instances
 * So, it is written as a singleton that attempts to only renders once
 *
 */
export function SessionPlayerModal(): JSX.Element | null {
    const { activeSessionRecording } = useValues(sessionPlayerModalLogic())
    const { closeSessionPlayer } = useActions(sessionPlayerModalLogic())

    // activeSessionRecording?.matching_events should always be a single element array
    // but, we're filtering and using flatMap just in case
    const eventUUIDs =
        activeSessionRecording?.matching_events
            ?.filter((matchingEvents) => {
                return matchingEvents.session_id === activeSessionRecording?.id
            })
            .flatMap((matchedRecording) => matchedRecording.events.map((x) => x.uuid)) || []

    const logicProps: SessionRecordingPlayerLogicProps = {
        playerKey: 'modal',
        sessionRecordingId: activeSessionRecording?.id || '',
        autoPlay: true,
        matchingEventsMatchType: {
            matchType: 'uuid',
            eventUUIDs: eventUUIDs,
        },
    }

    const { isFullScreen } = useValues(sessionRecordingPlayerLogic(logicProps))

    const [isTheGlobalRenderedModal, setIsTheGlobalRenderedModal] = useState(false)

    useEffect(() => {
        if (sessionPlayerModalSingletonRendered) {
            setIsTheGlobalRenderedModal(false)
        } else {
            sessionPlayerModalSingletonRendered = true
            setIsTheGlobalRenderedModal(true)
        }

        return () => {
            if (isTheGlobalRenderedModal) {
                sessionPlayerModalSingletonRendered = false
            }
        }
    }, [])

    if (!isTheGlobalRenderedModal) {
        return null
    }

    return (
        <LemonModal
            isOpen={!!activeSessionRecording}
            onClose={closeSessionPlayer}
            simple
            title=""
            width={1600}
            fullScreen={isFullScreen}
            closable={!isFullScreen}
        >
            <header>
                {activeSessionRecording ? (
                    <BindLogic logic={sessionRecordingPlayerLogic} props={logicProps}>
                        <PlayerMeta />
                    </BindLogic>
                ) : null}
            </header>
            <LemonModal.Content embedded>
                {activeSessionRecording?.id && <SessionRecordingPlayer {...logicProps} noMeta noBorder />}
            </LemonModal.Content>
        </LemonModal>
    )
}
