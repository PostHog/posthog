import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { Dayjs, dayjs } from 'lib/dayjs'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { urls } from 'scenes/urls'

import { EventType } from '~/types'

export default function ViewRecordingButton({
    sessionId,
    timestamp,
    inModal = false,
    ...props
}: Pick<LemonButtonProps, 'size' | 'type' | 'data-attr' | 'fullWidth' | 'className' | 'disabledReason'> & {
    sessionId: string
    timestamp?: string | Dayjs
    // whether to open in a modal or navigate to the replay page
    inModal?: boolean
}): JSX.Element {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)

    return (
        <LemonButton
            to={inModal ? undefined : urls.replaySingle(sessionId)}
            onClick={
                inModal
                    ? () => {
                          const fiveSecondsBeforeEvent = timestamp ? dayjs(timestamp).valueOf() - 5000 : 0
                          openSessionPlayer({ id: sessionId }, Math.max(fiveSecondsBeforeEvent, 0))
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
