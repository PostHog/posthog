import { Dayjs, dayjs } from 'lib/dayjs'
import { shortTimeZone } from 'lib/utils'

function formatStringFor(d: Dayjs): string {
    const today = dayjs()
    if (d.isSame(today, 'year')) {
        return 'DD/MMM, HH:mm:ss'
    }
    return 'DD/MM/YYYY HH:mm:ss'
}

export function SimpleTimeLabel({ startTime, isUTC }: { startTime: string | number; isUTC: boolean }): JSX.Element {
    let d = dayjs(startTime)
    if (isUTC) {
        d = d.tz('UTC')
    }

    return (
        <div className="overflow-hidden text-ellipsis text-xs text-muted shrink-0">
            {d.format(formatStringFor(d))} {isUTC ? 'UTC' : shortTimeZone(undefined, dayjs(d).toDate())}
        </div>
    )
}
