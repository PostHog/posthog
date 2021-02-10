import React from 'react'
import { PlayCircleOutlined } from '@ant-design/icons'
import { SessionType } from '~/types'
import { fromParams, toParams } from 'lib/utils'
import { Link } from 'lib/components/Link'
import './Sessions.scss'

interface SessionsPlayerButtonProps {
    session: SessionType
}

export const sessionPlayerUrl = (sessionRecordingId: string): string => {
    return `${location.pathname}?${toParams({ ...fromParams(), sessionRecordingId })}`
}

export function SessionsPlayerButton({ session }: SessionsPlayerButtonProps): JSX.Element | null {
    if (!session.session_recordings) {
        return null
    }

    return (
        <>
            {session.session_recordings.map(({ id, viewed }) => (
                <Link
                    to={sessionPlayerUrl(id)}
                    className={`sessions-player-button ${viewed ? 'viewed' : ''}`}
                    key={id}
                    onClick={(event) => event.stopPropagation()}
                >
                    <PlayCircleOutlined />
                </Link>
            ))}
        </>
    )
}
