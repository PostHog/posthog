import { useActions, useValues } from 'kea'

import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { nextWideningSuggestion } from './troubleshootingSuggestions'

export const SessionRecordingsPlaylistTroubleshooting = (): JSX.Element => {
    const { setHideViewedRecordings } = useActions(playerSettingsLogic)
    const { hiddenRecordingsCount, filters } = useValues(sessionRecordingsPlaylistLogic)
    const { setShowSettings, setFilters } = useActions(sessionRecordingsPlaylistLogic)

    const widening = nextWideningSuggestion(filters.date_from)

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
                    {widening && (
                        <li>
                            <LemonButton
                                type="secondary"
                                fullWidth={true}
                                size="xsmall"
                                data-attr="replay-empty-state-widen-date-range"
                                onClick={() => setFilters({ date_from: widening.value })}
                            >
                                {widening.label}
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
