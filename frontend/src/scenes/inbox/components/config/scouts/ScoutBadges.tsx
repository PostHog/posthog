import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { getScoutOrigin } from '../../../utils/scoutRunsWindow'

/** Canonical (PostHog-maintained) vs Custom (team-authored) scout badge. */
export function ScoutOriginBadge({ skillName }: { skillName: string }): JSX.Element {
    const origin = getScoutOrigin(skillName)
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
