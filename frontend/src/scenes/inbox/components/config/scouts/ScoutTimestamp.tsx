import { TZLabel } from 'lib/components/TZLabel'

/** Scout-standard timestamp: detailed date+time that self-updates across the "Today"/"Just now"
 * boundaries, no hover popover (these render inside button headers), small muted text. */
export function ScoutTimestamp({ time }: { time: string }): JSX.Element {
    return (
        <TZLabel
            time={time}
            showPopover={false}
            formatDate="MMMM DD, YYYY"
            formatTime="h:mm:ss A"
            className="text-[11px] text-muted"
        />
    )
}
