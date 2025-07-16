import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'
import { Dayjs } from 'lib/dayjs'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { ReactNode } from 'react'

import { MatchedRecording } from '~/types'

import ViewRecordingTrigger from './ViewRecordingTrigger'

export default function ViewRecordingButton({
    sessionId,
    recordingStatus,
    timestamp,
    label,
    inModal = false,
    checkIfViewed = false,
    matchingEvents,
    ...props
}: Pick<LemonButtonProps, 'size' | 'type' | 'data-attr' | 'fullWidth' | 'className' | 'loading'> & {
    sessionId: string | undefined
    recordingStatus?: string
    timestamp?: string | Dayjs
    // whether to open in a modal or navigate to the replay page
    inModal?: boolean
    checkIfViewed?: boolean
    label?: ReactNode
    matchingEvents?: MatchedRecording[]
}): JSX.Element {
    return (
        <ViewRecordingTrigger
            sessionId={sessionId}
            recordingStatus={recordingStatus}
            timestamp={timestamp}
            inModal={inModal}
            checkIfViewed={checkIfViewed}
            matchingEvents={matchingEvents}
        >
            {(onClick, link, disabledReason, maybeUnwatchedIndicator) => (
                <LemonButton
                    disabledReason={disabledReason}
                    to={link}
                    onClick={onClick}
                    sideIcon={<IconPlayCircle />}
                    {...props}
                >
                    <div className="flex items-center gap-2">
                        <span>{label ? label : 'View recording'}</span>
                        {maybeUnwatchedIndicator}
                    </div>
                </LemonButton>
            )}
        </ViewRecordingTrigger>
    )
}
