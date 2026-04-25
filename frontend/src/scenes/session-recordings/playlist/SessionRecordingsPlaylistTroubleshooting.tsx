import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useRef } from 'react'

import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'

import { RecordingUniversalFilters } from '~/types'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export const SessionRecordingsPlaylistTroubleshooting = (): JSX.Element => {
    const { setHideViewedRecordings } = useActions(playerSettingsLogic)
    const { hiddenRecordingsCount, userScopedFilterHints, sessionRecordingsResponseLoading } =
        useValues(sessionRecordingsPlaylistLogic)
    const { setShowSettings, setFilters } = useActions(sessionRecordingsPlaylistLogic)
    const { hidesViewed, filterTestAccounts, isDefaultDateRange, anyActive } = userScopedFilterHints

    const lastReportedRef = useRef<string | null>(null)
    useEffect(() => {
        if (sessionRecordingsResponseLoading || !anyActive) {
            return
        }
        const signature = `${hidesViewed ? 'v' : ''}|${filterTestAccounts ? 't' : ''}|${
            isDefaultDateRange ? 'd' : ''
        }|${hiddenRecordingsCount}`
        if (lastReportedRef.current === signature) {
            return
        }
        lastReportedRef.current = signature
        posthog.capture('session_replay_empty_with_user_scoped_filters', {
            hides_viewed: hidesViewed,
            filter_test_accounts: filterTestAccounts,
            is_default_date_range: isDefaultDateRange,
            hidden_recordings_count: hiddenRecordingsCount,
        })
    }, [
        sessionRecordingsResponseLoading,
        anyActive,
        hidesViewed,
        filterTestAccounts,
        isDefaultDateRange,
        hiddenRecordingsCount,
    ])

    const clearAllUserScopedFilters = (): void => {
        if (hidesViewed) {
            setHideViewedRecordings(false)
        }
        const filterUpdates: Partial<RecordingUniversalFilters> = {}
        if (filterTestAccounts) {
            filterUpdates.filter_test_accounts = false
        }
        if (isDefaultDateRange) {
            filterUpdates.date_from = '-30d'
        }
        if (Object.keys(filterUpdates).length > 0) {
            setFilters(filterUpdates)
        }
    }

    const showClearAll = [hidesViewed, filterTestAccounts, isDefaultDateRange].filter(Boolean).length > 1

    return (
        <>
            <h3 className="title text-secondary mb-0">No matching recordings</h3>
            {anyActive && (
                <p className="text-xs text-secondary mb-1">
                    Some filters are scoped to you and may be hiding recordings your colleagues can see.
                </p>
            )}
            <div className="flex flex-col deprecated-space-y-2">
                <ul className="deprecated-space-y-1">
                    {hidesViewed && hiddenRecordingsCount > 0 && (
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
                    {hidesViewed && hiddenRecordingsCount === 0 && (
                        <li>
                            <LemonButton
                                type="secondary"
                                fullWidth={true}
                                size="xsmall"
                                data-attr="replay-empty-state-troubleshooting-stop-hiding-viewed"
                                onClick={() => setHideViewedRecordings(false)}
                            >
                                Stop hiding viewed recordings
                            </LemonButton>
                        </li>
                    )}
                    {filterTestAccounts && (
                        <li>
                            <LemonButton
                                type="secondary"
                                fullWidth={true}
                                size="xsmall"
                                data-attr="replay-empty-state-troubleshooting-include-test-accounts"
                                onClick={() => setFilters({ filter_test_accounts: false })}
                            >
                                Include recordings from test accounts
                            </LemonButton>
                        </li>
                    )}
                    {isDefaultDateRange && (
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
                    )}
                    {showClearAll && (
                        <li>
                            <LemonButton
                                type="primary"
                                fullWidth={true}
                                size="xsmall"
                                data-attr="replay-empty-state-troubleshooting-clear-user-scoped-filters"
                                onClick={clearAllUserScopedFilters}
                            >
                                Clear filters that may be hiding recordings
                            </LemonButton>
                        </li>
                    )}
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
