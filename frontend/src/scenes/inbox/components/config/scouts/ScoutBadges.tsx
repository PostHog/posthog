import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type {
    ScoutOriginEnumApi,
    SignalScoutConfigApi as SignalScoutConfig,
} from 'products/signals/frontend/generated/api.schemas'

/**
 * Where the scout stands with the system writers that can pause it: the failure breaker
 * (`repeated_failures`) or the inactivity sweep (`no_output` / `ignored`), plus the sweep's
 * warning state (`pending_pause`). Without it a scout that has silently stopped looks the same
 * as one a person turned off. Nothing renders for a healthy scout or a user pause.
 */
export function ScoutLifecycleBadge({ config }: { config: SignalScoutConfig }): JSX.Element | null {
    if (config.status === 'paused_by_system') {
        if (config.pause_reason === 'repeated_failures') {
            return (
                <Tooltip
                    title={
                        <span>
                            This scout paused itself because its last few runs all failed. It retries about once a day
                            and resumes its normal schedule on the first successful run. Turn it on to resume it right
                            away.
                        </span>
                    }
                >
                    <LemonTag type="warning" size="small">
                        Paused
                    </LemonTag>
                </Tooltip>
            )
        }
        if (config.pause_reason === 'no_output' || config.pause_reason === 'ignored') {
            const pausedOn = config.status_changed_at
                ? `Paused on ${dayjs(config.status_changed_at).format('MMMM D, YYYY')}`
                : 'Paused'
            const why =
                config.pause_reason === 'ignored'
                    ? 'because nothing came of its recent reports'
                    : 'after two weeks without surfacing anything'
            return (
                <Tooltip title={`${pausedOn} ${why}. Switch it back on to resume it.`}>
                    <LemonTag type="warning" size="small">
                        Paused
                    </LemonTag>
                </Tooltip>
            )
        }
        return null
    }
    if (config.status === 'pending_pause') {
        // The two warnings say different things at a glance: `ignored` schedules a pause and can
        // apply to a scout that files plenty of reports, so labeling it "Quiet" would misread as
        // a benign watchdog.
        const ignored = config.pause_reason === 'ignored'
        const title = ignored
            ? "Nothing has come of this scout's recent reports, so it pauses in about a week unless that changes. Turn on 'Opt out of auto-pause' in its settings to leave it running."
            : "This scout hasn't surfaced anything in the last two weeks. It keeps running, but check that it's watching the right things. Turn on 'Opt out of auto-pause' in its settings if quiet is expected."
        return (
            <Tooltip title={title}>
                <LemonTag type="caution" size="small">
                    {ignored ? 'Pausing soon' : 'Quiet'}
                </LemonTag>
            </Tooltip>
        )
    }
    return null
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
