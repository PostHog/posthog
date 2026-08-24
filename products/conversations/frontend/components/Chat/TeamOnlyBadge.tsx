import { IconLock } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

/**
 * Marks a thread entry as team-only. Shared because the thread's whole purpose is sending things to
 * customers, so "the customer cannot see this" has to look identical wherever it appears: one badge,
 * one tooltip, no chance of two surfaces drifting into two different-looking promises.
 *
 * `label` varies because what's being withheld varies: a note someone wrote, versus an agent's findings.
 *
 * `tone` varies for a different reason. The lock, the tooltip and the shape stay fixed, so the promise
 * is still one thing; only the colour follows whoever wrote the entry, matching the note it sits above.
 */
export type TeamOnlyTone = 'teammate' | 'agent' | 'discussion'

const TONE_CLASSES: Record<TeamOnlyTone, string> = {
    teammate: 'text-warning-dark bg-warning-highlight',
    agent: 'text-ai bg-ai/10',
    discussion: 'text-accent bg-accent-highlight-secondary',
}

export function TeamOnlyBadge({ label, tone = 'teammate' }: { label: string; tone?: TeamOnlyTone }): JSX.Element {
    return (
        <Tooltip title="Only visible to your team">
            <span className={`inline-flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded ${TONE_CLASSES[tone]}`}>
                <IconLock className="text-xs" />
                {label}
            </span>
        </Tooltip>
    )
}
