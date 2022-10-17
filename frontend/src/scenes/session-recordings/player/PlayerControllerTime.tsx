import { Tooltip } from 'antd'
import { capitalizeFirstLetter, colonDelimitedDuration } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { ONE_FRAME_MS, sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { seekbarLogic } from './seekbarLogic'
import { SessionRecordingPlayerProps } from '~/types'
import { LemonButton } from '@posthog/lemon-ui'
import { useKeyHeld } from 'lib/hooks/useKeyHeld'
import { IconSkipBackward } from 'lib/components/icons'
import clsx from 'clsx'

export function Timestamp({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const { currentPlayerTime, sessionPlayerData } = useValues(
        sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    )
    const { isScrubbing, scrubbingTime } = useValues(seekbarLogic({ sessionRecordingId, playerKey }))

    return (
        <div className="whitespace-nowrap mr-4">
            {colonDelimitedDuration(((isScrubbing ? scrubbingTime : currentPlayerTime) ?? 0) / 1000)} /{' '}
            {colonDelimitedDuration(Math.floor((sessionPlayerData?.metadata?.recordingDurationMs ?? 0) / 1000))}
        </div>
    )
}

export function SeekSkip({
    sessionRecordingId,
    playerKey,
    direction,
}: SessionRecordingPlayerProps & { direction: 'forward' | 'backward' }): JSX.Element {
    const { seekForward, seekBackward } = useActions(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const { jumpTimeMs } = useValues(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))

    const keysHeld = useKeyHeld()
    const altKeyHeld = keysHeld.has('Alt')
    const jumpTimeSeconds = altKeyHeld ? 1 : jumpTimeMs / 1000
    const altKeyName = navigator.platform.includes('Mac') ? '⌥' : 'Alt'

    return (
        <Tooltip
            placement="top"
            overlayInnerStyle={{ minHeight: 'auto' }}
            overlay={
                <div className="text-center">
                    {!altKeyHeld ? (
                        <>
                            {capitalizeFirstLetter(direction)} {jumpTimeSeconds}s (<kbd>→ right arrow</kbd>) <br />
                        </>
                    ) : null}
                    {capitalizeFirstLetter(direction)} 1 frame ({ONE_FRAME_MS}ms) (<kbd>{altKeyName} + →</kbd>)
                </div>
            }
        >
            <LemonButton
                status="primary-alt"
                size="small"
                onClick={() => (direction === 'forward' ? seekForward() : seekBackward())}
            >
                <div className="PlayerControlSeekIcon">
                    <span className="PlayerControlSeekIcon__seconds">{jumpTimeSeconds}</span>
                    <IconSkipBackward
                        className={clsx('PlayerControlSeekIcon__icon', {
                            'PlayerControlSeekIcon__icon--forward': direction === 'forward',
                        })}
                    />
                </div>
            </LemonButton>
        </Tooltip>
    )
}
