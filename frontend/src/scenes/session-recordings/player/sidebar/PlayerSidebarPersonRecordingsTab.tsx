import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { urls } from 'scenes/urls'

import { SessionRecordingType } from '~/types'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { playerPersonRecordingsLogic } from './playerPersonRecordingsLogic'

export function PlayerSidebarPersonRecordingsTab(): JSX.Element {
    const { logicProps, sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    const { recordings, recordingsResponseLoading, hasMore, hasLoaded, loadError, loadMoreError } = useValues(
        playerPersonRecordingsLogic(logicProps)
    )
    const { loadRecordings, loadMoreRecordings } = useActions(playerPersonRecordingsLogic(logicProps))

    if (recordingsResponseLoading && recordings.length === 0) {
        return (
            <div className="p-4">
                <WrappingLoadingSkeleton fullWidth>
                    <div aria-hidden>Loading</div>
                </WrappingLoadingSkeleton>
            </div>
        )
    }

    if (loadError) {
        return (
            <div className="p-4 deprecated-space-y-2">
                <p className="text-muted text-sm">Could not load this person's recordings.</p>
                <LemonButton size="small" type="secondary" onClick={() => loadRecordings({})}>
                    Try again
                </LemonButton>
            </div>
        )
    }

    if (hasLoaded && recordings.length <= 1) {
        return <p className="p-4 text-muted text-sm">This is the only recording for this person.</p>
    }

    return (
        <div className="p-2 deprecated-space-y-1">
            {recordings.map((recording) => (
                <RecordingRow
                    key={recording.id}
                    recording={recording}
                    isCurrent={recording.id === sessionRecordingId}
                />
            ))}
            {hasMore && (
                <>
                    {loadMoreError && (
                        <p className="text-danger text-xs text-center">Could not load older recordings.</p>
                    )}
                    <LemonButton
                        fullWidth
                        center
                        size="small"
                        type="secondary"
                        loading={recordingsResponseLoading}
                        onClick={() => loadMoreRecordings({})}
                    >
                        {loadMoreError ? 'Try again' : 'Load older recordings'}
                    </LemonButton>
                </>
            )}
        </div>
    )
}

function RecordingRow({ recording, isCurrent }: { recording: SessionRecordingType; isCurrent: boolean }): JSX.Element {
    const content = (
        <div className="flex items-center justify-between gap-2 w-full min-w-0">
            <div className="flex items-center gap-2 min-w-0">
                <TZLabel time={recording.start_time} className="text-sm" />
                {isCurrent && (
                    <LemonTag type="highlight" size="small">
                        Playing now
                    </LemonTag>
                )}
            </div>
            <span className="text-xs text-muted flex-shrink-0">
                {humanFriendlyDuration(recording.recording_duration)}
            </span>
        </div>
    )

    if (isCurrent) {
        return <div className="flex items-center rounded px-2 py-1 bg-accent-highlight-secondary">{content}</div>
    }

    return (
        <Link
            to={urls.replaySingle(recording.id)}
            className="flex items-center rounded px-2 py-1 hover:bg-fill-highlight-50"
        >
            {content}
        </Link>
    )
}
