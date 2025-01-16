import clsx from 'clsx'
import { Dayjs, dayjs } from 'lib/dayjs'
import { shortTimeZone } from 'lib/utils'

function formatStringFor(d: Dayjs): string {
    const today = dayjs()
    if (d.isSame(today, 'year')) {
        return 'DD/MMM, HH:mm:ss'
    }
    return 'DD/MM/YYYY HH:mm:ss'
}

export function SimpleTimeLabel({
    startTime,
    isUTC,
    muted = true,
    size = 'xsmall',
}: {
    startTime: string | number | Dayjs
    isUTC: boolean
    muted?: boolean
    size?: 'small' | 'xsmall'
}): JSX.Element {
    let d = dayjs(startTime)
    if (isUTC) {
        d = d.tz('UTC')
    }

    return (
        <div
            className={clsx(
                'overflow-hidden text-ellipsis shrink-0',
                muted && 'text-muted',
                size === 'xsmall' && 'text-xs',
                size === 'small' && 'text-sm'
            )}
        >
            {d.format(formatStringFor(d))} {isUTC ? 'UTC' : shortTimeZone(undefined, dayjs(d).toDate())}
        </div>
    )
}
