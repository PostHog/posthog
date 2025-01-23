import clsx from 'clsx'
import { Dayjs, dayjs } from 'lib/dayjs'
import { shortTimeZone } from 'lib/utils'
import { memo } from 'react'
import { TimestampFormat } from 'scenes/session-recordings/player/playerSettingsLogic'

function formattedReplayTime(
    time: string | number | Dayjs | null | undefined,
    timestampFormat: TimestampFormat
): string {
    if (time == null) {
        return '--/--/----, 00:00:00'
    }

    let d = dayjs(time)
    const isUTC = timestampFormat === TimestampFormat.UTC
    if (isUTC) {
        d = d.tz('UTC')
    }
    const formatted = d.format(formatStringFor(d))
    const timezone = isUTC ? 'UTC' : shortTimeZone(undefined, d.toDate())
    return `${formatted} ${timezone}`
}

function formatStringFor(d: Dayjs): string {
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
}: {
    startTime: string | number | Dayjs | undefined
    timestampFormat: TimestampFormat
    muted?: boolean
    size?: 'small' | 'xsmall'
}): JSX.Element {
    return (
        <div
            className={clsx(
                'overflow-hidden text-ellipsis shrink-0',
                muted && 'text-muted',
                size === 'xsmall' && 'text-xs',
                size === 'small' && 'text-sm'
            )}
        >
            {formattedReplayTime(startTime, timestampFormat)}
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
            prevProps.size === nextProps.size
        )
    }
)
