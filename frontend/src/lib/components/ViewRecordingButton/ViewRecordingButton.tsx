import { useActions, useValues } from 'kea'
import { ReactNode, useEffect } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonButton, LemonButtonProps, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { Dayjs, dayjs } from 'lib/dayjs'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { UnwatchedIndicator } from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import { urls } from 'scenes/urls'

import { MatchedRecording } from '~/types'

import { sessionRecordingViewedLogic } from './sessionRecordingViewedLogic'

export default function ViewRecordingButton({
    sessionId,
    recordingStatus,
    recordingDuration,
    minimumDuration,
    timestamp,
    label,
    inModal = false,
    checkIfViewed = false,
    matchingEvents,
    ...props
}: Pick<LemonButtonProps, 'size' | 'type' | 'data-attr' | 'fullWidth' | 'className' | 'loading'> & {
    sessionId: string | undefined
    recordingStatus?: string
    recordingDuration?: number
    minimumDuration?: number
    timestamp?: string | Dayjs
    // whether to open in a modal or navigate to the replay page
    inModal?: boolean
    checkIfViewed?: boolean
    label?: ReactNode
    matchingEvents?: MatchedRecording[]
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
    const warningReason = recordingWarningReason(recordingDuration, minimumDuration)
    const to = inModal ? undefined : urls.replaySingle(sessionId ?? '')

    const sideIcon = warningReason ? (
        <Tooltip title={warningReason}>
            <IconWarning />
        </Tooltip>
    ) : (
        <IconPlayCircle />
    )

    return (
        <LemonButton
            disabledReason={disabledReason}
            to={to}
            onClick={onClick}
            sideIcon={sideIcon}
            {...props}
            targetBlank
        >
            <div className="flex items-center gap-2 whitespace-nowrap">
                <span>{label ? label : 'View recording'}</span>
                {maybeUnwatchedIndicator}
            </div>
        </LemonButton>
    )
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

const recordingWarningReason = (
    recordingDuration: number | undefined,
    minimumDuration: number | undefined
): string | undefined => {
    if (recordingDuration && minimumDuration && recordingDuration < minimumDuration) {
        const minimumDurationInSeconds = minimumDuration / 1000
        return `There is a chance this recording was not captured because the event happened earlier than the ${minimumDurationInSeconds}s minimum session duration.`
    }
    return undefined
}
