import { Link, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Dayjs, dayjs } from 'lib/dayjs'
import { ReactNode, useEffect } from 'react'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { UnwatchedIndicator } from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import { urls } from 'scenes/urls'

import { MatchedRecording } from '~/types'

import { sessionRecordingViewedLogic } from './sessionRecordingViewedLogic'

export default function ViewRecordingTrigger({
    sessionId,
    recordingStatus,
    timestamp,
    inModal = false,
    checkIfViewed = false,
    matchingEvents,
    children,
}: {
    sessionId: string | undefined
    recordingStatus: string | undefined
    timestamp?: string | Dayjs
    // whether to open in a modal or navigate to the replay page
    inModal?: boolean
    checkIfViewed?: boolean
    label?: ReactNode
    matchingEvents?: MatchedRecording[]
    children: (
        onClick: () => void,
        link: string | undefined,
        disabledReason: JSX.Element | string | null,
        maybeUnwatchedIndicator?: JSX.Element | null
    ) => JSX.Element
}): JSX.Element {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const { recordingViewed, recordingViewedLoading } = useValues(
        sessionRecordingViewedLogic({ sessionRecordingId: sessionId ?? '' })
    )
    const { loadRecordingViewed, userClickedThrough } = useActions(
        sessionRecordingViewedLogic({ sessionRecordingId: sessionId ?? '' })
    )

    useEffect(() => {
        if (checkIfViewed && loadRecordingViewed) {
            loadRecordingViewed()
        }
    }, [checkIfViewed, loadRecordingViewed])

    let maybeUnwatchedIndicator = null
    if (checkIfViewed) {
        if (recordingViewedLoading) {
            maybeUnwatchedIndicator = <Spinner />
        } else if (!recordingViewed?.viewed) {
            maybeUnwatchedIndicator = <UnwatchedIndicator otherViewersCount={recordingViewed?.otherViewers || 0} />
        }
    }
    const onClick = (): void => {
        userClickedThrough()
        if (inModal) {
            const fiveSecondsBeforeEvent = timestamp ? dayjs(timestamp).valueOf() - 5000 : 0
            openSessionPlayer(
                { id: sessionId ?? '', matching_events: matchingEvents ?? undefined },
                Math.max(fiveSecondsBeforeEvent, 0)
            )
        }
    }
    const disabledReason = recordingDisabledReason(sessionId, recordingStatus)
    const link = inModal ? undefined : urls.replaySingle(sessionId ?? '')

    return children(onClick, link, disabledReason, maybeUnwatchedIndicator)
}

const recordingDisabledReason = (
    sessionId: string | undefined,
    recordingStatus: string | undefined
): JSX.Element | string | null => {
    if (!sessionId) {
        return (
            <>
                No session ID associated with this event.{' '}
                <Link to="https://posthog.com/docs/data/sessions#automatically-sending-session-ids">Learn how</Link> to
                set it on all events.
            </>
        )
    } else if (recordingStatus && !['active', 'sampled', 'buffering'].includes(recordingStatus)) {
        return (
            <>
                Replay was not active when capturing this event.{' '}
                <Link to="https://posthog.com/docs/session-replay/troubleshooting#recordings-are-not-being-captured">
                    Learn why
                </Link>{' '}
                not all recordings are captured.
            </>
        )
    }

    return null
}
