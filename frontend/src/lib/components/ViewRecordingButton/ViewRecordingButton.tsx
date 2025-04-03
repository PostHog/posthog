import { LemonButton, LemonButtonProps, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Dayjs, dayjs } from 'lib/dayjs'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { ReactNode, useEffect } from 'react'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { UnwatchedIndicator } from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import { urls } from 'scenes/urls'

import { MatchedRecording } from '~/types'

import { sessionRecordingViewedLogic } from './sessionRecordingViewedLogic'

export default function ViewRecordingButton({
    sessionId,
    timestamp,
    label,
    inModal = false,
    checkIfViewed = false,
    matchingEvents,
    ...props
}: Pick<LemonButtonProps, 'size' | 'type' | 'data-attr' | 'fullWidth' | 'className' | 'disabledReason' | 'loading'> & {
    sessionId: string | undefined
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

    return (
        <LemonButton
            disabledReason={sessionId ? undefined : 'No session ID provided'}
            to={inModal ? undefined : urls.replaySingle(sessionId ?? '')}
            onClick={() => {
                userClickedThrough()
                if (inModal) {
                    const fiveSecondsBeforeEvent = timestamp ? dayjs(timestamp).valueOf() - 5000 : 0
                    openSessionPlayer(
                        { id: sessionId ?? '', matching_events: matchingEvents ?? undefined },
                        Math.max(fiveSecondsBeforeEvent, 0)
                    )
                }
            }}
            sideIcon={<IconPlayCircle />}
            {...props}
        >
            <div className="flex items-center gap-2">
                <span>{label ? label : 'View recording'}</span>
                {maybeUnwatchedIndicator}
            </div>
        </LemonButton>
    )
}

export const mightHaveRecording = (properties: { $session_id?: string; $recording_status?: string }): boolean => {
    return properties.$session_id
        ? properties.$recording_status
            ? ['active', 'sampled'].includes(properties.$recording_status)
            : true
        : false
}
