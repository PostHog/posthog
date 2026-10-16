import { useActions, useValues } from 'kea'

import { IconLive } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { cn } from 'lib/utils/css-classes'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

export function FollowLive(): JSX.Element | null {
    const { followLive, sessionPlayerMetaData, featureFlags } = useValues(sessionRecordingPlayerLogic)
    const { setFollowLive } = useActions(sessionRecordingPlayerLogic)

    if (!featureFlags[FEATURE_FLAGS.REPLAY_FOLLOW_LIVE] || !sessionPlayerMetaData?.ongoing) {
        return null
    }

    return (
        <LemonButton
            size="xsmall"
            active={followLive}
            onClick={() => setFollowLive(!followLive)}
            tooltip={
                followLive
                    ? 'Stop following live'
                    : 'Follow live. New activity plays as it arrives, about 30 seconds behind.'
            }
            icon={<IconLive className={cn('text-xl', followLive && 'text-danger motion-safe:animate-pulse')} />}
            data-attr={followLive ? 'recording-follow-live-stop' : 'recording-follow-live-start'}
        >
            Live
        </LemonButton>
    )
}
