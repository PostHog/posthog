import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

export function AccountContextDate({ date }: { date: string }): JSX.Element {
    if (!date) {
        return <span className="text-secondary">Unknown</span>
    }
    return (
        <TZLabel
            time={dayjs.utc(date)}
            displayTimezone="UTC"
            formatDate="MMM D, YYYY"
            formatTime=""
            showPopover={false}
        />
    )
}
