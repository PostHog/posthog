import clsx from 'clsx'
import { memo } from 'react'

import { Dayjs, dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { shortTimeZone } from 'lib/utils'
import { TimestampFormat } from 'scenes/session-recordings/player/playerSettingsLogic'

function formattedReplayTime(
    time: string | number | Dayjs | null | undefined,
    timestampFormat: TimestampFormat,
    timeOnly?: boolean
): string {
    if (time == null) {
        return timeOnly ? '00:00:00' : '--/--/----, 00:00:00'
    }

    let d = dayjs(time)
    const isUTC = timestampFormat === TimestampFormat.UTC
    if (isUTC) {
        d = d.tz('UTC')
    }
    const formatted = d.format(formatStringFor(d, timeOnly))
    const timezone = isUTC ? 'UTC' : shortTimeZone(undefined, d.toDate())
    return `${formatted} ${timezone}`
}

function formatStringFor(d: Dayjs, timeOnly?: boolean): string {
    if (timeOnly) {
        return 'HH:mm:ss'
    }

    const today = dayjs()
    if (d.isSame(today, 'year')) {
        return 'DD/MMM, HH:mm:ss'
    }
    return 'DD/MM/YYYY HH:mm:ss'
}

const truncateToSeconds = (time: string | number | Dayjs): number => {
    switch (typeof time) {
        case 'number':
            return Math.floor(time / 1000) * 1000
        case 'string':
            return Math.floor(new Date(time).getTime() / 1000) * 1000
        default:
            return time.startOf('second').valueOf()
    }
}

export function _SimpleTimeLabel({
    startTime,
    timestampFormat,
    muted = true,
    size = 'xsmall',
    containerSize,
}: {
    startTime: string | number | Dayjs | undefined
    timestampFormat: TimestampFormat
    muted?: boolean
    size?: 'small' | 'xsmall'
    containerSize?: 'small' | 'normal'
}): JSX.Element {
    const formattedTime = formattedReplayTime(startTime, timestampFormat, containerSize === 'small')
    return (
        <div
            className={clsx(
                'overflow-hidden text-ellipsis shrink-0',
                muted && 'text-muted',
                size === 'xsmall' && 'text-xs',
                size === 'small' && 'text-sm'
            )}
        >
            {containerSize === 'small' ? (
                <Tooltip title={formattedReplayTime(startTime, timestampFormat, false)}>{formattedTime}</Tooltip>
            ) : (
                formattedTime
            )}
        </div>
    )
}

export const SimpleTimeLabel = memo(
    _SimpleTimeLabel,
    // we can truncate time when considering whether to re-render the component as we only go down to seconds in dispay,
    // but it will be called with multiple millisecond values between each second
    // in local tests this rendered at least 4x less (400 vs 1600 renders)
    // this gets better for recordings with more activity
    (prevProps, nextProps) => {
        const prevStartTimeTruncated = prevProps.startTime ? truncateToSeconds(prevProps.startTime) : null
        const nextStartTimeTruncated = nextProps.startTime ? truncateToSeconds(nextProps.startTime) : null

        return (
            prevStartTimeTruncated === nextStartTimeTruncated &&
            prevProps.timestampFormat === nextProps.timestampFormat &&
            prevProps.muted === nextProps.muted &&
            prevProps.size === nextProps.size &&
            prevProps.containerSize === nextProps.containerSize
        )
    }
)
