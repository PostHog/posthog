import { TZLabel } from 'lib/components/TZLabel'

export function AccountContextDate({ date }: { date: string }): JSX.Element {
    if (!date) {
        return <span className="text-secondary">Unknown</span>
    }
    return <TZLabel time={date} displayTimezone="UTC" formatDate="MMM D, YYYY" formatTime="" />
}
