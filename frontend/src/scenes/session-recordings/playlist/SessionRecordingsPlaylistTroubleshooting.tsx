import { useActions, useValues } from 'kea'

import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export const SessionRecordingsPlaylistTroubleshooting = (): JSX.Element => {
    const { hideViewedRecordings } = useValues(playerSettingsLogic)
    const { setHideViewedRecordings } = useActions(playerSettingsLogic)
    const { hiddenRecordingsCount, totalFiltersCount, isScopedByCaller } = useValues(sessionRecordingsPlaylistLogic)
    const { setShowSettings, setFilters, resetFilters } = useActions(sessionRecordingsPlaylistLogic)
    const { currentTeam } = useValues(teamLogic)

    // Only an explicit `false` counts: the flag is absent from some team payloads, and
    // reading that as "no events" would tell a working project its SDK is broken.
    const hasNoEvents = currentTeam?.ingested_event === false

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
                    <LemonDivider dashed={true} />
                    {hasNoEvents && (
                        <>
                            <li>
                                <Link
                                    to={urls.onboarding({
                                        productKey: ProductKey.SESSION_REPLAY,
                                        stepKey: OnboardingStepKey.INSTALL,
                                    })}
                                    data-attr="replay-empty-state-troubleshooting-no-events"
                                >
                                    This project has no events yet. Check your installation
                                </Link>
                            </li>
                            <LemonDivider dashed={true} />
                        </>
                    )}
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
