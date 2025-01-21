import { LemonButton, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useKeyHeld } from 'lib/hooks/useKeyHeld'
import { IconSkipBackward } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter, colonDelimitedDuration } from 'lib/utils'
import { SimpleTimeLabel } from 'scenes/session-recordings/components/SimpleTimeLabel'
import { ONE_FRAME_MS, sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { HotKeyOrModifier } from '~/types'

import { playerSettingsLogic, TimestampFormat } from '../playerSettingsLogic'
import { seekbarLogic } from './seekbarLogic'

function RelativeTimestampLabel(): JSX.Element {
    const { logicProps, currentPlayerTime, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const { isScrubbing, scrubbingTime } = useValues(seekbarLogic(logicProps))

    const startTimeSeconds = ((isScrubbing ? scrubbingTime : currentPlayerTime) ?? 0) / 1000
    const endTimeSeconds = Math.floor(sessionPlayerData.durationMs / 1000)

    const fixedUnits = endTimeSeconds > 3600 ? 3 : 2

    return (
        <div className="flex gap-0.5">
            <span>{colonDelimitedDuration(startTimeSeconds, fixedUnits)}</span>
            <span>/</span>
            <span>{colonDelimitedDuration(endTimeSeconds, fixedUnits)}</span>
        </div>
    )
}

export function Timestamp(): JSX.Element {
    const { logicProps, currentTimestamp, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const { isScrubbing, scrubbingTime } = useValues(seekbarLogic(logicProps))
    const { timestampFormat } = useValues(playerSettingsLogic)

    const scrubbingTimestamp = sessionPlayerData.start?.valueOf()
        ? scrubbingTime + sessionPlayerData.start?.valueOf()
        : undefined

    return (
        <div data-attr="recording-timestamp" className="text-center whitespace-nowrap font-mono text-xs">
            {timestampFormat === TimestampFormat.Relative ? (
                <RelativeTimestampLabel />
            ) : (
                <SimpleTimeLabel
                    startTime={isScrubbing ? scrubbingTimestamp : currentTimestamp}
                    timestampFormat={timestampFormat}
                />
            )}
        </div>
    )
}

export function SeekSkip({ direction }: { direction: 'forward' | 'backward' }): JSX.Element {
    const { seekForward, seekBackward } = useActions(sessionRecordingPlayerLogic)
    const { jumpTimeMs } = useValues(sessionRecordingPlayerLogic)

    const altKeyHeld = useKeyHeld('Alt')
    const jumpTimeSeconds = altKeyHeld ? 1 : jumpTimeMs / 1000

    const arrowKey: Partial<Record<HotKeyOrModifier, true>> = {}
    if (direction === 'forward') {
        arrowKey.arrowright = true
    }
    if (direction === 'backward') {
        arrowKey.arrowleft = true
    }

    return (
        <Tooltip
            placement="top"
            title={
                <div className="text-center">
                    {!altKeyHeld ? (
                        <>
                            {capitalizeFirstLetter(direction)} {jumpTimeSeconds}s <KeyboardShortcut {...arrowKey} />
                            <br />
                        </>
                    ) : null}
                    {capitalizeFirstLetter(direction)} 1 frame ({ONE_FRAME_MS}ms){' '}
                    <KeyboardShortcut option {...arrowKey} />
                </div>
            }
        >
            <LemonButton
                data-attr={`seek-skip-${direction}`}
                size="xsmall"
                noPadding={true}
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
