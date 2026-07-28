import { IconLock } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

/**
 * Marks a thread entry as team-only. Shared because the thread's whole purpose is sending things to
 * customers, so "the customer cannot see this" has to look identical wherever it appears: one badge,
 * one tooltip, no chance of two surfaces drifting into two different-looking promises.
 *
 * `label` varies because what's being withheld varies: a note someone wrote, versus an agent's findings.
 */
export function TeamOnlyBadge({ label }: { label: string }): JSX.Element {
    return (
        <Tooltip title="Only visible to your team">
            <span className="inline-flex items-center gap-0.5 text-xs text-warning-dark bg-warning-highlight px-1.5 py-0.5 rounded">
                <IconLock className="text-xs" />
                {label}
            </span>
        </Tooltip>
    )
}
