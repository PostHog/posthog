import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconClock } from '@posthog/icons'
import { LemonButton, LemonButtonProps, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { useKeyHeld } from 'lib/hooks/useKeyHeld'
import { IconSkipBackward } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter, colonDelimitedDuration, shortTimeZone } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { formatLocalizedDate } from 'lib/utils/dateTimeUtils'
import { SimpleTimeLabel } from 'scenes/session-recordings/components/SimpleTimeLabel'
import {
    ONE_SECOND_MS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { HotKeyOrModifier } from '~/types'

import { TimestampFormat, playerSettingsLogic } from '../playerSettingsLogic'
import { seekbarLogic } from './seekbarLogic'

const TIMESTAMP_FORMAT_LABELS: Record<TimestampFormat, string> = {
    [TimestampFormat.Relative]: 'Relative',
    [TimestampFormat.UTC]: 'UTC',
    [TimestampFormat.Device]: 'Device',
}

function formatTimestampForTooltip(timestamp: number | undefined, format: TimestampFormat): string {
    if (timestamp === undefined) {
        return '--:--:--'
    }
    const d = format === TimestampFormat.UTC ? dayjs(timestamp).tz('UTC') : dayjs(timestamp)
    const formatted = d.format(`${formatLocalizedDate()}, HH:mm:ss`)
    const timezone = format === TimestampFormat.UTC ? 'UTC' : shortTimeZone(undefined, d.toDate())
    return `${formatted} ${timezone}`
}

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
        <span className="text-muted text-xs">{current}</span>
    ) : (
        <span className="text-muted text-xs">{fullDisplay}</span>
    )
}

export function Timestamp({
    size,
    noPadding,
}: { size: 'small' | 'normal' } & Pick<LemonButtonProps, 'noPadding'>): JSX.Element {
    const { logicProps, currentTimestamp, currentPlayerTimeSeconds, sessionPlayerData } =
        useValues(sessionRecordingPlayerLogic)
    const { isScrubbing, scrubbingTime, scrubbingTimeSeconds } = useValues(seekbarLogic(logicProps))
    const { timestampFormat } = useValues(playerSettingsLogic)
    const { setTimestampFormat } = useActions(playerSettingsLogic)
    const [isHovered, setIsHovered] = useState(false)

    const scrubbingTimestamp = sessionPlayerData.start?.valueOf()
        ? scrubbingTime + sessionPlayerData.start?.valueOf()
        : undefined

    const activeTimestamp = isScrubbing ? scrubbingTimestamp : currentTimestamp
    const relativeTimeSeconds = (isScrubbing ? scrubbingTimeSeconds : currentPlayerTimeSeconds) ?? 0
    const relativeTime = colonDelimitedDuration(relativeTimeSeconds, 2)

    const values = Object.values(TimestampFormat)
    const nextIndex = (values.indexOf(timestampFormat) + 1) % values.length
    const nextFormat = values[nextIndex]

    const tooltipContent = (
        <div className="space-y-1">
            {values.map((format) => {
                const isCurrent = format === timestampFormat
                const label = TIMESTAMP_FORMAT_LABELS[format]
                const value =
                    format === TimestampFormat.Relative
                        ? relativeTime
                        : formatTimestampForTooltip(activeTimestamp, format)

                return (
                    <div
                        key={format}
                        className={cn('flex justify-between gap-4 px-1 -mx-1 rounded', isCurrent && 'bg-white/20')}
                    >
                        <span>{label}</span>
                        <span className="font-mono text-right">{value}</span>
                    </div>
                )
            })}
            <div className="opacity-75 text-xs border-t border-white/20 pt-1 mt-1">
                Click to show time in {TIMESTAMP_FORMAT_LABELS[nextFormat].toLowerCase()} format
            </div>
        </div>
    )

    return (
        <Tooltip title={tooltipContent} placement="top" visible={isHovered}>
            <LemonButton
                data-attr="recording-timestamp"
                className="text-center whitespace-nowrap font-mono text-xs inline"
                noPadding={noPadding}
                icon={<IconClock className="text-muted" />}
                onMouseEnter={() => setIsHovered(true)}
                onMouseLeave={() => setIsHovered(false)}
                onClick={() => {
                    setTimestampFormat(nextFormat)
                }}
            >
                {timestampFormat === TimestampFormat.Relative ? (
                    <RelativeTimestampLabel size={size} />
                ) : (
                    <SimpleTimeLabel
                        startTime={activeTimestamp}
                        timestampFormat={timestampFormat}
                        containerSize={size}
                    />
                )}
            </LemonButton>
        </Tooltip>
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
            delayMs={100}
            title={
                <div className="text-center">
                    {!altKeyHeld ? (
                        <>
                            {capitalizeFirstLetter(direction)} {jumpTimeSeconds}s <KeyboardShortcut {...arrowKey} />
                            <br />
                        </>
                    ) : null}
                    {capitalizeFirstLetter(direction)} 1s <KeyboardShortcut option {...arrowKey} />
                </div>
            }
        >
            <LemonButton
                data-attr={`seek-skip-${direction}`}
                size="xsmall"
                noPadding={true}
                onClick={() => {
                    const amount = altKeyHeld ? ONE_SECOND_MS : undefined
                    direction === 'forward' ? seekForward(amount) : seekBackward(amount)
                }}
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
