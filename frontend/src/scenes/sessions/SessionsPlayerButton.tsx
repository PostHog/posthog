import React from 'react'
import { PlayCircleOutlined } from '@ant-design/icons'
import { SessionType } from '~/types'
import { fromParams, toParams } from 'lib/utils'
import { Link } from 'lib/components/Link'
import './Sessions.scss'

interface SessionsPlayerButtonProps {
    session: SessionType
}

export default function SessionsPlayerButton({ session }: SessionsPlayerButtonProps): JSX.Element | null {
    const sessionPlayerUrl = (sessionRecordingId: string): string => {
        return `${location.pathname}?${toParams({ ...fromParams(), sessionRecordingId })}`
    }

    if (!session.session_recording_ids) {
        return null
    }

    return (
        <>
            {session.session_recording_ids.map((sessionRecordingId: string) => (
                <Link
                    to={sessionPlayerUrl(sessionRecordingId)}
                    className="sessions-player-button"
                    key={sessionRecordingId}
                    onClick={(event) => event.stopPropagation()}
                >
                    <PlayCircleOutlined />
                </Link>
            ))}
        </>
    )
}
