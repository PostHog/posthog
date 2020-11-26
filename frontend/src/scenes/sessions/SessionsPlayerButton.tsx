import React from 'react'
import { PlayCircleOutlined } from '@ant-design/icons'
import { SessionType } from '~/types'

import './Sessions.scss'
import { fromParams, toParams } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

function sessionPlayerUrl(sessionRecordingId: string, baseUrl: string): string {
    const params = { ...fromParams(), sessionRecordingId }
    return baseUrl + '?' + toParams(params)
}

interface SessionsPlayerButtonProps {
    session: SessionType
}

export default function SessionsPlayerButton({ session }: SessionsPlayerButtonProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!session.session_recording_ids) {
        return null
    }

    return (
        <>
            {session.session_recording_ids.map((sessionRecordingId: string) => (
                <Link
                    to={sessionPlayerUrl(
                        sessionRecordingId,
                        featureFlags['full-page-player'] ? '/sessions/play' : location.pathname
                    )}
                    target={featureFlags['full-page-player'] ? '_blank' : undefined}
                    className="sessions-player-button"
                    key={sessionRecordingId}
                >
                    <PlayCircleOutlined />
                </Link>
            ))}
        </>
    )
}
