import { PreviewCard } from '@base-ui/react/preview-card'
import { ReactNode, useContext } from 'react'

import { TodayPreviewCardContext } from './todayPreviewCardContext'
import { TodayPreviewPayload } from './todayPreviewCards'

// Desktop's timings: the first card waits for the pointer to rest, and a short close delay lets it cross to the card.
const OPEN_DELAY_MS = 400
const CLOSE_DELAY_MS = 100

/**
 * Makes a sidebar row show the shared hover card. The card reads `payload` from the active trigger,
 * so keep it referentially stable: a new object writes it to the card's store again.
 */
export function TodayPreviewTrigger({
    payload,
    children,
}: {
    payload: TodayPreviewPayload
    children: ReactNode
}): JSX.Element {
    const card = useContext(TodayPreviewCardContext)
    if (!card) {
        return <>{children}</>
    }
    return (
        <PreviewCard.Trigger
            handle={card.handle}
            payload={payload}
            delay={OPEN_DELAY_MS}
            closeDelay={CLOSE_DELAY_MS}
            render={<div className="min-w-0" />}
        >
            {children}
        </PreviewCard.Trigger>
    )
}
