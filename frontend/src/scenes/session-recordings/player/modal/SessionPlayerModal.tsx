import React from 'react'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { useActions, useValues } from 'kea'
import { sessionPlayerModalLogic } from './sessionPlayerModalLogic'
import { LemonModal } from '@posthog/lemon-ui'
import { PlayerMetaV3 } from '../PlayerMeta'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

export function SessionPlayerModal(): JSX.Element | null {
    const { activeSessionRecording } = useValues(sessionPlayerModalLogic())
    const { closeSessionPlayer } = useActions(sessionPlayerModalLogic())
    const { isFullScreen } = useValues(
        sessionRecordingPlayerLogic({ sessionRecordingId: activeSessionRecording?.id || '', playerKey: 'modal' })
    )
    return (
        <LemonModal
            isOpen={!!activeSessionRecording}
            onClose={closeSessionPlayer}
            simple
            title={''}
            width={880}
            fullScreen={isFullScreen}
            closable={!isFullScreen}
        >
            <header>
                {activeSessionRecording ? (
                    <PlayerMetaV3 playerKey="modal" sessionRecordingId={activeSessionRecording?.id} />
                ) : null}
            </header>
            <LemonModal.Content embedded>
                <div className="SessionPlayerModal">
                    {activeSessionRecording?.id && (
                        <SessionRecordingPlayer
                            playerKey="modal"
                            sessionRecordingId={activeSessionRecording?.id}
                            matching={activeSessionRecording?.matching_events}
                            includeMeta={false}
                        />
                    )}
                </div>
            </LemonModal.Content>
        </LemonModal>
    )
}
