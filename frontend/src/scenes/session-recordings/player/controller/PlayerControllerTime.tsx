import { useActions, useValues } from 'kea'

import { LemonButton, LemonButtonProps, Tooltip } from '@posthog/lemon-ui'

import { useKeyHeld } from 'lib/hooks/useKeyHeld'
import { IconSkipBackward } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter, colonDelimitedDuration } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { SimpleTimeLabel } from 'scenes/session-recordings/components/SimpleTimeLabel'
import { ONE_FRAME_MS, sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { HotKeyOrModifier } from '~/types'

import { TimestampFormat, playerSettingsLogic } from '../playerSettingsLogic'
import { seekbarLogic } from './seekbarLogic'

function RelativeTimestampLabel({ size }: { size: 'small' | 'normal' }): JSX.Element {
    const { logicProps, currentPlayerTimeSeconds, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const { isScrubbing, scrubbingTimeSeconds } = useValues(seekbarLogic(logicProps))

    const startTimeSeconds = (isScrubbing ? scrubbingTimeSeconds : currentPlayerTimeSeconds) ?? 0
    const endTimeSeconds = Math.floor(sessionPlayerData.durationMs / 1000)

    const fixedUnits = endTimeSeconds > 3600 ? 3 : 2

    const current = colonDelimitedDuration(startTimeSeconds, fixedUnits)
    const total = colonDelimitedDuration(endTimeSeconds, fixedUnits)
    const fullDisplay = (
        <div className="flex gap-0.5">
            <span>{current}</span>
            <span>/</span>
            <span>{total}</span>
        </div>
    )
    return size === 'small' ? (
        <Tooltip title={fullDisplay}>
            <span className="text-muted text-xs">{current}</span>
        </Tooltip>
    ) : (
        <span className="text-muted text-xs">{fullDisplay}</span>
    )
}

export function Timestamp({
    size,
    noPadding,
}: { size: 'small' | 'normal' } & Pick<LemonButtonProps, 'noPadding'>): JSX.Element {
    const { logicProps, currentTimestamp, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const { isScrubbing, scrubbingTime } = useValues(seekbarLogic(logicProps))
    const { timestampFormat } = useValues(playerSettingsLogic)
    const { setTimestampFormat } = useActions(playerSettingsLogic)

    const scrubbingTimestamp = sessionPlayerData.start?.valueOf()
        ? scrubbingTime + sessionPlayerData.start?.valueOf()
        : undefined

    return (
        <LemonButton
            data-attr="recording-timestamp"
            className="text-center whitespace-nowrap font-mono text-xs inline"
            noPadding={noPadding}
            onClick={() => {
                const values = Object.values(TimestampFormat)
                const nextIndex = (values.indexOf(timestampFormat) + 1) % values.length
                setTimestampFormat(values[nextIndex])
            }}
        >
            {timestampFormat === TimestampFormat.Relative ? (
                <RelativeTimestampLabel size={size} />
            ) : (
                <SimpleTimeLabel
                    startTime={isScrubbing ? scrubbingTimestamp : currentTimestamp}
                    timestampFormat={timestampFormat}
                    containerSize={size}
                />
            )}
        </LemonButton>
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
                className="ph-no-rageclick"
            >
                <div className="PlayerControlSeekIcon">
                    <span className="PlayerControlSeekIcon__seconds">{jumpTimeSeconds}</span>
                    <IconSkipBackward
                        className={cn('text-2xl PlayerControlSeekIcon__icon', {
                            'PlayerControlSeekIcon__icon--forward': direction === 'forward',
                        })}
                    />
                </div>
            </LemonButton>
        </Tooltip>
    )
}
