import React from 'react'
import { PlayCircleOutlined } from '@ant-design/icons'
import { SessionType } from '~/types'

import './Sessions.scss'
import { fromParams, toParams } from 'lib/utils'
import { Link } from 'lib/components/Link'

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

    return (
        <>
            {session.session_recording_ids.map((sessionRecordingId: string) => (
                <Link
                    to={sessionPlayerUrl(sessionRecordingId)}
                    className="sessions-player-button"
                    key={sessionRecordingId}
                >
                    <PlayCircleOutlined />
                </Link>
            ))}
        </>
    )
}
