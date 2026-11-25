import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

export function ProductUsageWeekRange({
    columnKey,
    partial = false,
}: {
    columnKey: string
    partial?: boolean
}): JSX.Element {
    return (
        <>
            <span>Week of </span>
            <TZLabel time={columnKey} formatDate="MMM D" formatTime="" />
            <span> to </span>
            <TZLabel
                time={dayjs(columnKey).add(1, 'week').subtract(1, 'day').format('YYYY-MM-DD')}
                formatDate="MMM D, YYYY"
                formatTime=""
            />
            {partial && <span> (to date)</span>}
        </>
    )
}
