import { Tooltip } from 'antd'
import { capitalizeFirstLetter, colonDelimitedDuration } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { ONE_FRAME_MS, sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { seekbarLogic } from './seekbarLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { useKeyHeld } from 'lib/hooks/useKeyHeld'
import { IconSkipBackward } from 'lib/lemon-ui/icons'
import clsx from 'clsx'

export function Timestamp(): JSX.Element {
    const { logicProps, currentPlayerTime, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const { isScrubbing, scrubbingTime } = useValues(seekbarLogic(logicProps))

    const startTimeSeconds = ((isScrubbing ? scrubbingTime : currentPlayerTime) ?? 0) / 1000
    const endTimeSeconds = Math.floor(sessionPlayerData.durationMs / 1000)

    const fixedUnits = endTimeSeconds > 3600 ? 3 : 2

    return (
        <div className="whitespace-nowrap mr-4">
            {colonDelimitedDuration(startTimeSeconds, fixedUnits)} /{' '}
            {colonDelimitedDuration(endTimeSeconds, fixedUnits)}
        </div>
    )
}

export function SeekSkip({ direction }: { direction: 'forward' | 'backward' }): JSX.Element {
    const { seekForward, seekBackward } = useActions(sessionRecordingPlayerLogic)
    const { jumpTimeMs } = useValues(sessionRecordingPlayerLogic)

    const altKeyHeld = useKeyHeld('Alt')
    const jumpTimeSeconds = altKeyHeld ? 1 : jumpTimeMs / 1000
    const altKeyName = navigator.platform.includes('Mac') ? '⌥' : 'Alt'

    const arrowSymbol = direction === 'forward' ? '→' : '←'
    const arrowName = direction === 'forward' ? 'right' : 'left'

    return (
        <Tooltip
            placement="top"
            overlayInnerStyle={{ minHeight: 'auto' }}
            overlay={
                <div className="text-center">
                    {!altKeyHeld ? (
                        <>
                            {capitalizeFirstLetter(direction)} {jumpTimeSeconds}s (
                            <kbd>
                                {arrowSymbol} {arrowName} arrow
                            </kbd>
                            ) <br />
                        </>
                    ) : null}
                    {capitalizeFirstLetter(direction)} 1 frame ({ONE_FRAME_MS}ms) (
                    <kbd>
                        {altKeyName} + {arrowSymbol}
                    </kbd>
                    )
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
