import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import {
    RecordingsListLoadError,
    sessionRecordingsPlaylistLogic,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

export const ListLoadErrorBanner = ({ error }: { error: RecordingsListLoadError }): JSX.Element => {
    const { sessionRecordingsResponseLoading } = useValues(sessionRecordingsPlaylistLogic)
    const { loadSessionRecordings } = useActions(sessionRecordingsPlaylistLogic)

    return (
        <LemonBanner
            type="error"
            action={{
                children: 'Try again',
                // Forced, so the retry reads the rows again instead of answering from the memo of
                // an earlier load for the same filters.
                onClick: () => loadSessionRecordings(undefined, undefined, true),
                loading: sessionRecordingsResponseLoading,
                'data-attr': 'session-recordings-list-retry',
            }}
        >
            {/* A request that never reached PostHog carries the browser's own wording, which
                says nothing a viewer can act on. */}
            {error.status === null
                ? "Couldn't load recordings. Check your connection and try again."
                : `Couldn't load recordings: ${error.detail}`}
        </LemonBanner>
    )
}
