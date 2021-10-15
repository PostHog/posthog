import React from 'react'

import { Drawer } from 'lib/components/Drawer'
import { SessionsPlay } from 'scenes/sessions/SessionsPlay'
import { SessionRecordingPlayerV2 } from 'scenes/sessionRecordings/player/SessionRecordingPlayerV2'
import { useValues } from 'kea'
import { ArrowTopLeftOutlined } from 'lib/components/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Button } from 'antd'

interface SessionPlayerDrawerProps {
    isPersonPage?: boolean
    onClose: () => void
}

export function SessionPlayerDrawer({ isPersonPage = false, onClose }: SessionPlayerDrawerProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <Drawer destroyOnClose visible width="100%" onClose={onClose}>
            <>
                <Button type="link" onClick={onClose}>
                    <ArrowTopLeftOutlined /> Back to{' '}
                    {isPersonPage
                        ? 'persons'
                        : featureFlags[FEATURE_FLAGS.REMOVE_SESSIONS]
                        ? 'sessions recordings'
                        : 'sessions'}
                </Button>
                {featureFlags[FEATURE_FLAGS.NEW_SESSIONS_PLAYER] ? <SessionRecordingPlayerV2 /> : <SessionsPlay />}
            </>
        </Drawer>
    )
}
