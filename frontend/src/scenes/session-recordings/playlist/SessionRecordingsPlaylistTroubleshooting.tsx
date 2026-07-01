import { useActions, useValues } from 'kea'

import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export const SessionRecordingsPlaylistTroubleshooting = (): JSX.Element => {
    const { setHideViewedRecordings } = useActions(playerSettingsLogic)
    const { hiddenRecordingsCount } = useValues(sessionRecordingsPlaylistLogic)
    const { setShowSettings, setFilters } = useActions(sessionRecordingsPlaylistLogic)
    const { currentTeam } = useValues(teamLogic)

    // When replay isn't enabled there simply won't be any recordings — surface that directly
    // instead of the generic troubleshooting tips, which read as a dead-end for new projects.
    if (currentTeam && !currentTeam.session_recording_opt_in) {
        return (
            <>
                <h3 className="title text-secondary mb-0">Session recordings aren't enabled</h3>
                <div className="flex flex-col deprecated-space-y-2">
                    <p className="mb-0">
                        This project isn't capturing recordings yet, so there's nothing to show here.
                    </p>
                    <LemonButton type="primary" fullWidth={true} size="small" to={urls.replaySettings('replay')}>
                        Enable session recordings
                    </LemonButton>
                </div>
            </>
        )
    }

    return (
        <>
            <h3 className="title text-secondary mb-0">No matching recordings</h3>
            <div className="flex flex-col deprecated-space-y-2">
                <ul className="deprecated-space-y-1">
                    {hiddenRecordingsCount > 0 && (
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
                                Show {hiddenRecordingsCount} hidden recordings
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
                    <LemonDivider dashed={true} />
                    <li>
                        <Link to="https://posthog.com/docs/session-replay/data-retention" target="_blank">
                            Recordings might be outside the retention period
                        </Link>
                    </li>
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
