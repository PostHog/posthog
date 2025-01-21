import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { Dayjs, dayjs } from 'lib/dayjs'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { MatchingEventsMatchType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'

import { EventType } from '~/types'

export default function ViewRecordingButton({
    sessionId,
    timestamp,
    inModal = false,
    matchingEventsMatchType,
    ...props
}: Pick<LemonButtonProps, 'size' | 'type' | 'data-attr' | 'fullWidth' | 'className' | 'disabledReason'> & {
    sessionId: string
    timestamp?: string | Dayjs
    // whether to open in a modal or navigate to the replay page
    inModal?: boolean
    matchingEventsMatchType?: MatchingEventsMatchType
}): JSX.Element {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)

    return (
        <LemonButton
            to={inModal ? undefined : urls.replaySingle(sessionId)}
            onClick={
                inModal
                    ? () => {
                          const fiveSecondsBeforeEvent = timestamp ? dayjs(timestamp).valueOf() - 5000 : 0
                          openSessionPlayer(sessionId, Math.max(fiveSecondsBeforeEvent, 0), matchingEventsMatchType)
                      }
                    : undefined
            }
            sideIcon={<IconPlayCircle />}
            {...props}
        >
            View recording
        </LemonButton>
    )
}

export const mightHaveRecording = (properties: EventType['properties']): boolean => {
    return properties.$session_id
        ? properties.$recording_status
            ? properties.$recording_status === 'active'
            : true
        : false
}
