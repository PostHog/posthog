import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { BindLogic, useActions, useValues } from 'kea'
import { sessionPlayerModalLogic } from './sessionPlayerModalLogic'
import { LemonModal } from '@posthog/lemon-ui'
import { PlayerMeta } from '../PlayerMeta'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

export function SessionPlayerModal(): JSX.Element | null {
    const { activeSessionRecording } = useValues(sessionPlayerModalLogic())
    const { closeSessionPlayer } = useActions(sessionPlayerModalLogic())

    const logicProps = {
        playerKey: 'modal',
        sessionRecordingId: activeSessionRecording?.id || '',
        matching: activeSessionRecording?.matching_events,
    }

    const { isFullScreen } = useValues(sessionRecordingPlayerLogic(logicProps))

    return (
        <LemonModal
            isOpen={!!activeSessionRecording}
            onClose={closeSessionPlayer}
            simple
            title={''}
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
                {activeSessionRecording?.id && <SessionRecordingPlayer {...logicProps} includeMeta={false} noBorder />}
            </LemonModal.Content>
        </LemonModal>
    )
}
