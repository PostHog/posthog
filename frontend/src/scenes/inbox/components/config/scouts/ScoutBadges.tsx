import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import type { ScoutOriginEnumApi } from 'products/signals/frontend/generated/api.schemas'

/**
 * Shown when a scout paused itself after failing repeatedly (`status=paused_by_system`,
 * `pause_reason=repeated_failures`). Without it the pause is only visible in the API
 * response, and a scout that has silently stopped looks the same as one a person turned off.
 */
export function ScoutPausedBadge(): JSX.Element {
    return (
        <Tooltip
            title={
                <span>
                    This scout paused itself because its last few runs all failed. It retries about once a day and
                    resumes its normal schedule on the first successful run. Turn it on to resume it right away.
                </span>
            }
        >
            <LemonTag type="warning" size="small">
                Paused
            </LemonTag>
        </Tooltip>
    )
}

/** Canonical (PostHog-maintained) vs Custom (team-authored) scout badge. */
export function ScoutOriginBadge({ origin }: { origin: ScoutOriginEnumApi }): JSX.Element {
    return (
        <Tooltip
            title={
                origin === 'canonical'
                    ? 'Part of the standard scout troop built and maintained by PostHog'
                    : 'A scout your team created as a signals-scout-* skill in this project'
            }
        >
            <LemonTag type={origin === 'canonical' ? 'muted' : 'highlight'} size="small">
                {origin === 'canonical' ? 'Canonical' : 'Custom'}
            </LemonTag>
        </Tooltip>
    )
}
