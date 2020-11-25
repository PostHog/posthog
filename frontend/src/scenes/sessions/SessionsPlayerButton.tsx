import React from 'react'
import { useActions } from 'kea'
import { PlayCircleOutlined } from '@ant-design/icons'
import { SessionType } from '~/types'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'

import './Sessions.scss'
import { fromParams, toParams } from 'lib/utils'

function sessionPlayerUrl(sessionRecordingId: string): string {
    const params = { ...fromParams(), sessionRecordingId }
    return location.pathname + '?' + toParams(params)
}

interface SessionsPlayerButtonProps {
    session: SessionType
}

export default function SessionsPlayerButton({ session }: SessionsPlayerButtonProps): JSX.Element | null {
    if (!session.session_recording_ids) {
        return null
    }

    const { loadSessionPlayer } = useActions(sessionsTableLogic)

    return (
        <>
            {session.session_recording_ids.map((sessionRecordingId: string) => (
                <a
                    href={sessionPlayerUrl(sessionRecordingId)}
                    className="sessions-player-button"
                    key={sessionRecordingId}
                    onClick={(event: React.MouseEvent) => {
                        event.preventDefault()
                        event.stopPropagation()
                        loadSessionPlayer(sessionRecordingId)
                    }}
                >
                    <PlayCircleOutlined />
                </a>
            ))}
        </>
    )
}
