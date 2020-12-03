import React from 'react'
import { PlayCircleOutlined } from '@ant-design/icons'
import { SessionType } from '~/types'
import { fromParams, toParams } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import './Sessions.scss'

interface SessionsPlayerButtonProps {
    session: SessionType
}

export default function SessionsPlayerButton({ session }: SessionsPlayerButtonProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    const sessionPlayerUrl = (sessionRecordingId: string): string => {
        if (featureFlags['full-page-player']) {
            return `/sessions/play?${toParams({ id: sessionRecordingId })}`
        }
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
                    target={featureFlags['full-page-player'] ? '_blank' : undefined}
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
