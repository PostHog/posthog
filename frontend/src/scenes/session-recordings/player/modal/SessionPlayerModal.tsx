import { LemonModal } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'

import { PlayerMeta } from '../PlayerMeta'
import { sessionRecordingPlayerLogic, SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'
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
    const { activeSessionRecordingId, matchingEventsMatchType } = useValues(sessionPlayerModalLogic())
    const { closeSessionPlayer } = useActions(sessionPlayerModalLogic())

    const logicProps: SessionRecordingPlayerLogicProps = {
        playerKey: 'modal',
        sessionRecordingId: activeSessionRecordingId || '',
        autoPlay: true,
        matchingEventsMatchType: matchingEventsMatchType || { matchType: 'none' },
    }

    const { isFullScreen } = useValues(sessionRecordingPlayerLogic(logicProps))

    return (
        <LemonModal
            isOpen={!!activeSessionRecordingId}
            onClose={closeSessionPlayer}
            simple
            title=""
            width={1600}
            fullScreen={isFullScreen}
            closable={!isFullScreen}
            zIndex="1061"
            hideCloseButton={true}
        >
            <header>
                {activeSessionRecordingId ? (
                    <BindLogic logic={sessionRecordingPlayerLogic} props={logicProps}>
                        <PlayerMeta iconsOnly={false} />
                    </BindLogic>
                ) : null}
            </header>
            <LemonModal.Content embedded>
                {activeSessionRecordingId && <SessionRecordingPlayer {...logicProps} noMeta noBorder />}
            </LemonModal.Content>
        </LemonModal>
    )
}
