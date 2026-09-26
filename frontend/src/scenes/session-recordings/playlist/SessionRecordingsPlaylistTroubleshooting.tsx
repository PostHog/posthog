import { useActions, useValues } from 'kea'

import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { dayjs } from 'lib/dayjs'

import { ProductKey } from '~/queries/schema/schema-general'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export const SessionRecordingsPlaylistTroubleshooting = (): JSX.Element => {
    const { hideViewedRecordings } = useValues(playerSettingsLogic)
    const { setHideViewedRecordings } = useActions(playerSettingsLogic)
    const { hiddenRecordingsCount, totalFiltersCount, isScopedByCaller, olderRecordingsProbe } =
        useValues(sessionRecordingsPlaylistLogic)
    const { status: replaySetupStatus } = useValues(productSetupStatusLogic({ productKey: ProductKey.SESSION_REPLAY }))
    const { setShowSettings, setFilters, resetFilters } = useActions(sessionRecordingsPlaylistLogic)

    const recordingsAreHidden = hideViewedRecordings !== false
    const hasFilters = totalFiltersCount > 0
    // Clearing would drop the caller's scoping, leaving a list that no longer matches the surface.
    const canClearFilters = hasFilters && !isScopedByCaller
    // Setup detection scans the whole retention period, so the project has no recordings at all.
    const waitingForFirstRecording = !hasFilters && replaySetupStatus === 'waiting-for-data'
    const olderRecordings = !hasFilters && !waitingForFirstRecording ? olderRecordingsProbe : null

    if (waitingForFirstRecording) {
        return (
            <>
                <h3 className="title text-secondary mb-0">Waiting for the first recording</h3>
                <p className="mb-0">Session replay is on. New sessions show up here a few minutes after a visit.</p>
                <Link
                    to="https://posthog.com/docs/session-replay/troubleshooting#4-adtracking-blockers"
                    target="_blank"
                >
                    An ad blocker might be preventing recordings
                </Link>
            </>
        )
    }

    if (olderRecordings) {
        return (
            <>
                <h3 className="title text-secondary mb-0">No recordings in the last 3 days</h3>
                <p className="mb-0">{`The newest recording started ${dayjs(olderRecordings.newestStartTime).fromNow()}.`}</p>
                <LemonButton
                    type="secondary"
                    fullWidth={true}
                    size="xsmall"
                    data-attr="replay-empty-state-troubleshooting-show-older-recordings"
                    onClick={() => setFilters({ date_from: olderRecordings.dateFrom })}
                >
                    Show older recordings
                </LemonButton>
            </>
        )
    }

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
