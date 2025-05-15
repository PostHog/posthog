import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useState } from 'react'

import { EventType } from '~/types'

interface ViewVideoButtonProps
    extends Pick<
        LemonButtonProps,
        'size' | 'type' | 'data-attr' | 'fullWidth' | 'className' | 'disabledReason' | 'loading' | 'to'
    > {
    event?: EventType
    onClick?: (event: React.MouseEvent<HTMLButtonElement>) => void
}

export default function ViewVideoButton({ event, onClick, ...props }: ViewVideoButtonProps): JSX.Element {
    // const { reportVideoViewed } = useActions(eventUsageLogic)
    // const [isModalOpen, setIsModalOpen] = useState(false)

    const handleClick = (e: React.MouseEvent<HTMLButtonElement>): void => {
        if (onClick) {
            onClick(e)
            return
        }

        if (event?.properties?.video_clip) {
            // Report video view event
            // reportVideoViewed(event)
            
        }
    }

    const hasVideo = event?.properties?.video_clip

    return (
        <>
            <LemonButton
                sideIcon={<IconPlayCircle />}
                onClick={handleClick}
                disabledReason={!hasVideo ? 'No video available for this event' : props.disabledReason}
                {...props}
            >
                <div className="flex items-center gap-2">
                    <span>View Video</span>
                </div>
            </LemonButton>
        </>
    )
}
