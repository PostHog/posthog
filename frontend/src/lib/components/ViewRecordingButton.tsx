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
    ...props
}: Pick<LemonButtonProps, 'size' | 'type' | 'data-attr' | 'fullWidth' | 'className' | 'disabledReason'> & {
    sessionId: string
    timestamp?: string | Dayjs
}): JSX.Element {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)

    return (
        <LemonButton
            to={urls.replaySingle(sessionId)}
            onClick={() => {
                const fiveSecondsBeforeEvent = dayjs(timestamp).valueOf() - 5000
                openSessionPlayer({ id: sessionId }, Math.max(fiveSecondsBeforeEvent, 0))
            }}
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
