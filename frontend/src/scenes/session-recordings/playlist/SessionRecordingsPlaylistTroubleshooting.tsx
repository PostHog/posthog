import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'

import { useListTroubleshooting } from './useListTroubleshooting'

export const SessionRecordingsPlaylistTroubleshooting = (): JSX.Element => {
    const {
        heading,
        recordingsAreHidden,
        hiddenRecordingsCount,
        canClearFilters,
        showHiddenRecordings,
        clearFilters,
        searchLast30Days,
    } = useListTroubleshooting()

    return (
        <>
            <h3 className="title text-secondary mb-0">{heading}</h3>
            <div className="flex flex-col deprecated-space-y-2">
                <ul className="deprecated-space-y-1">
                    {recordingsAreHidden && (
                        <li>
                            <LemonButton
                                type="secondary"
                                fullWidth={true}
                                size="xsmall"
                                data-attr="replay-empty-state-troubleshooting-show-hidden-recordings"
                                onClick={showHiddenRecordings}
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
                                onClick={clearFilters}
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
                            onClick={searchLast30Days}
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
