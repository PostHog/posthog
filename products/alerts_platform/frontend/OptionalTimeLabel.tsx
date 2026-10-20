import { TZLabel } from 'lib/components/TZLabel'

export function OptionalTimeLabel({ time, fallback }: { time: string | null; fallback: string }): JSX.Element {
    return time ? <TZLabel time={time} /> : <span className="text-secondary">{fallback}</span>
}
