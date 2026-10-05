import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { dateFilterToText, dateStringToDayJs } from 'lib/utils/dateFilters'
import { isDate } from 'lib/utils/datetime'
import { shortTimeZone } from 'lib/utils/timezones'
import { teamLogic } from 'scenes/teamLogic'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export const SessionRecordingsPlaylistTroubleshooting = (): JSX.Element => {
    const { hideViewedRecordings } = useValues(playerSettingsLogic)
    const { setHideViewedRecordings } = useActions(playerSettingsLogic)
    const { hiddenRecordingsCount, totalFiltersCount, isScopedByCaller, filters } =
        useValues(sessionRecordingsPlaylistLogic)
    const { setShowSettings, setFilters, resetFilters } = useActions(sessionRecordingsPlaylistLogic)
    const { timezone } = useValues(teamLogic)

    const recordingsAreHidden = hideViewedRecordings !== false
    const hasFilters = totalFiltersCount > 0
    // A custom start time carries no offset, so the project time zone decides when it is.
    const dateFrom = dateStringToDayJs(filters.date_from ?? null, timezone)
    const startsInFuture = !!dateFrom && dateFrom.isAfter(dayjs())
    const timeZoneLabel = shortTimeZone(timezone) ?? timezone
    // The shared formatter counts days from the browser's date, which can differ from the project's.
    const dateRangeText =
        dateFrom && !filters.date_to && isDate.test(filters.date_from ?? '')
            ? dateFilterToText(dateFrom, dayjs().tz(timezone), null)
            : dateFilterToText(filters.date_from, filters.date_to, null)

    useEffect(() => {
        posthog.capture('recording list empty state shown', {
            hidden_recordings_count: hiddenRecordingsCount,
            total_filters_count: totalFiltersCount,
            empty_cause: startsInFuture ? 'future_start_date' : hasFilters ? 'filters' : 'no_filters',
        })
    }, [])
    // Clearing would drop the caller's scoping, leaving a list that no longer matches the surface.
    const canClearFilters = hasFilters && !isScopedByCaller

    return (
        <>
            <h3 className="title text-secondary mb-0">
                {startsInFuture
                    ? 'The date range starts in the future'
                    : hasFilters
                      ? 'No recordings match your filters'
                      : 'No recordings found'}
            </h3>
            {startsInFuture && dateFrom ? (
                <p className="text-secondary mb-0">
                    {`The range starts at ${dateFrom.format('MMMM D, h:mm A')} in the project time zone (${timeZoneLabel}). That time has not come yet, so no recordings can match. Pick an earlier start time.`}
                </p>
            ) : dateRangeText ? (
                <p className="text-secondary mb-0">{`Date range: ${dateRangeText} (${timeZoneLabel})`}</p>
            ) : null}
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
