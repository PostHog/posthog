import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'
import { Dayjs, dayjs } from 'lib/dayjs'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { ReactNode } from 'react'
import { urls } from 'scenes/urls'

import { MatchedRecording } from '~/types'

export default function ViewVideoButton({
    sessionId,
    timestamp,
    label,
    inModal = false,
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
    return (
        <LemonButton
            disabledReason={sessionId ? undefined : 'No session ID provided'}
            to={inModal ? undefined : urls.replaySingle(sessionId ?? '')}
            onClick={() => {
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
                <span>{label ? label : 'View video'}</span>
                {maybeUnwatchedIndicator}
            </div>
        </LemonButton>
    )
}
