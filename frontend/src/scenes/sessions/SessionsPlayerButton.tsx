import React from 'react'
import { useActions } from 'kea'
import { green } from '@ant-design/colors'
import { PlayCircleOutlined } from '@ant-design/icons'
import { SessionType } from '~/types'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'

interface SessionsPlayerButtonProps {
    session: SessionType
}

export default function SessionsPlayerButton({ session }: SessionsPlayerButtonProps): JSX.Element | null {
    // TODO: Work around no clickhouse support yet for session recording
    if (!session.session_recording_ids) {
        return null
    }

    const { loadSessionPlayer } = useActions(sessionsTableLogic)

    return (
        <>
            {session.session_recording_ids.map((sessionRecordingId: string) => (
                <PlayCircleOutlined
                    key={sessionRecordingId}
                    style={{ color: green.primary }}
                    onClick={(event: React.MouseEvent) => {
                        event.stopPropagation()
                        loadSessionPlayer(sessionRecordingId)
                    }}
                />
            ))}
        </>
    )
}
