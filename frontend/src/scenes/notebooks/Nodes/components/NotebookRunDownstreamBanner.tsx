import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

// Journey 10: shown on the cell whose run most recently landed, while any of its downstream
// cells are still stale. The action re-runs that downstream set in document order via the
// staleness logic's rooted chain; unrelated stale cells keep their warning but are not run.
export function NotebookRunDownstreamBanner({
    count,
    onRun,
    disabledReason,
}: {
    count: number
    onRun: () => void
    disabledReason?: string
}): JSX.Element {
    return (
        <LemonBanner
            type="info"
            className="mx-2 mt-1 p-2 text-xs"
            hideIcon
            action={{
                children: count === 1 ? 'Run downstream cell' : `Run downstream cells (${count})`,
                onClick: onRun,
                disabledReason,
                size: 'xsmall',
            }}
        >
            {count === 1
                ? '1 downstream cell is showing outdated results.'
                : `${count} downstream cells are showing outdated results.`}
        </LemonBanner>
    )
}
