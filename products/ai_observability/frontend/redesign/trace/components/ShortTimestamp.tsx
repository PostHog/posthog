import { TZLabel } from 'lib/components/TZLabel'

export interface ShortTimestampProps {
    time: string
}

export function ShortTimestamp({ time }: ShortTimestampProps): JSX.Element {
    return <TZLabel time={time} timestampStyle="absolute" formatDate="MMM D," formatTime="HH:mm" />
}
