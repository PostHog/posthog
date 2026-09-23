import { useActions, useValues } from 'kea'

import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { sessionRecordingRetentionDays, sessionRecordingRetentionLabel } from '../utils/sessionRecordingRetention'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

/**
 * The two facts that answer most "why is there no recording for this person" questions are whether
 * replay is on for the project and how far back recordings survive. Both are on the team, so state
 * them here instead of sending the reader to the docs to work them out.
 */
function ProjectReplayFacts(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)

    // Absent while the team loads, and absent from the public team payload on shared pages. Neither
    // means replay is off, so say nothing rather than telling someone with replay running that it is.
    const optIn = currentTeam?.session_recording_opt_in
    if (optIn === undefined) {
        return null
    }

    if (!optIn) {
        return (
            <>
                <LemonDivider dashed={true} />
                <li>
                    <div className="text-danger">Session replay is turned off for this project</div>
                    <div>No new sessions are being recorded.</div>
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        className="mt-1"
                        data-attr="replay-empty-state-troubleshooting-enable-replay"
                        to={urls.settings('project-replay')}
                    >
                        Turn on session replay
                    </LemonButton>
                </li>
            </>
        )
    }

    const retentionPeriod = currentTeam?.session_recording_retention_period
    const cutoff = dayjs().subtract(sessionRecordingRetentionDays(retentionPeriod), 'day')

    return (
        <>
            <LemonDivider dashed={true} />
            <li data-attr="replay-empty-state-troubleshooting-retention">
                {/* One text node each, so an in-page translation extension cannot detach a sibling. */}
                <Link to="https://posthog.com/docs/session-replay/data-retention" target="_blank">
                    {`Recordings are kept for ${sessionRecordingRetentionLabel(retentionPeriod)}`}
                </Link>
                <div>{`Sessions from before ${cutoff.format('D MMM YYYY')} have been deleted.`}</div>
            </li>
        </>
    )
}

export const SessionRecordingsPlaylistTroubleshooting = (): JSX.Element => {
    const { hideViewedRecordings } = useValues(playerSettingsLogic)
    const { setHideViewedRecordings } = useActions(playerSettingsLogic)
    const { hiddenRecordingsCount, totalFiltersCount, isScopedByCaller } = useValues(sessionRecordingsPlaylistLogic)
    const { setShowSettings, setFilters, resetFilters } = useActions(sessionRecordingsPlaylistLogic)

    const recordingsAreHidden = hideViewedRecordings !== false
    const hasFilters = totalFiltersCount > 0
    // Clearing would drop the caller's scoping, leaving a list that no longer matches the surface.
    const canClearFilters = hasFilters && !isScopedByCaller

    return (
        <>
            <h3 className="title text-secondary mb-0">
                {hasFilters ? 'No recordings match your filters' : 'No recordings found'}
            </h3>
            <div className="flex flex-col deprecated-space-y-2">
                <ul className="deprecated-space-y-1">
                    {recordingsAreHidden && (
                        <li>
                            <LemonButton
                                type="secondary"
                                fullWidth={true}
                                size="xsmall"
                                data-attr="replay-empty-state-troubleshooting-show-hidden-recordings"
                                onClick={() => {
                                    setShowSettings(true)
                                    setHideViewedRecordings(false)
                                }}
                            >
                                {hiddenRecordingsCount > 0
                                    ? `Show ${hiddenRecordingsCount} hidden recordings`
                                    : 'Show hidden recordings'}
                            </LemonButton>
                        </li>
                    )}
                    {canClearFilters && (
                        <li>
                            <LemonButton
                                type="secondary"
                                fullWidth={true}
                                size="xsmall"
                                data-attr="replay-empty-state-troubleshooting-clear-filters"
                                onClick={() => resetFilters()}
                            >
                                Clear filters
                            </LemonButton>
                        </li>
                    )}
                    <li>
                        <LemonButton
                            type="secondary"
                            fullWidth={true}
                            size="xsmall"
                            data-attr="expand-replay-listing-from-default-seven-days-to-twenty-one"
                            onClick={() => setFilters({ date_from: '-30d' })}
                        >
                            Search over the last 30 days
                        </LemonButton>
                    </li>
                    <ProjectReplayFacts />
                    <LemonDivider dashed={true} />
                    <li>
                        <Link
                            to="https://posthog.com/docs/session-replay/troubleshooting#4-adtracking-blockers"
                            target="_blank"
                        >
                            An ad blocker might be preventing recordings
                        </Link>
                    </li>
                </ul>
            </div>
        </>
    )
}
