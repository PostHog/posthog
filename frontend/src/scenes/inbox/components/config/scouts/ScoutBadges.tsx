import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { SignalScoutConfig } from '../../../types'
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

/** Shown only when a scout runs on schedule but holds back its findings. */
export function DryRunBadge({ config }: { config: SignalScoutConfig }): JSX.Element | null {
    if (config.emit) {
        return null
    }
    return (
        <Tooltip title="Runs on schedule but findings are not emitted to the Signals inbox">
            <LemonTag type="caution" size="small">
                Dry run
            </LemonTag>
        </Tooltip>
    )
}
