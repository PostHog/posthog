import { Progress } from '@posthog/quill'

/** A thin share bar: light track, accent fill. One style for every share column. */
export function WarehouseShareBar({ fraction, label }: { fraction: number; label: string }): JSX.Element {
    return (
        <Progress
            value={Math.min(100, Math.max(0, fraction * 100))}
            variant="info"
            className="w-16 shrink-0 [&_[data-slot=progress-track]]:h-0.5"
            aria-label={label}
        />
    )
}
