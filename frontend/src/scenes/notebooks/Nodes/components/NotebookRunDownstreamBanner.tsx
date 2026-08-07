import { IconInfo } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

// Journey 10: shown on the cell whose run most recently landed, while any of its downstream
// cells are still stale. The action re-runs that downstream set in document order via the
// staleness logic's rooted chain; unrelated stale cells keep their warning but are not run.
// Accent styling on purpose: this is a nudge to keep results consistent, not an error state.
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
        <div className="mx-2 mt-1 flex items-center gap-2 rounded border border-accent bg-accent-highlight-secondary p-2 text-xs">
            <LemonButton type="primary" size="xsmall" onClick={onRun} disabledReason={disabledReason}>
                {count === 1 ? 'Run downstream cell' : `Run downstream cells (${count})`}
            </LemonButton>
            <IconInfo className="shrink-0 text-sm text-accent" />
            <span>
                {count === 1
                    ? '1 downstream cell may be showing outdated data'
                    : `${count} downstream cells may be showing outdated data`}
            </span>
        </div>
    )
}
