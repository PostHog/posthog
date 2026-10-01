import { PreviewCard } from '@base-ui/react/preview-card'
import { ReactNode, useMemo, useRef, useState } from 'react'

import { Card } from '@posthog/quill'

import { TodayPreviewCard, TodayPreviewCardContext } from './todayPreviewCardContext'
import { TodayPreviewPayload } from './todayPreviewCards'
import { TodaySessionHoverCard } from './TodaySessionHoverCard'
import { TodaySpaceHoverCard } from './TodaySpaceHoverCard'

/**
 * One hover card for every row in the sidebar, like PostHog Desktop. The rows are only triggers on a shared handle,
 * and Base UI skips the open delay when the pointer moves to another trigger of an open card,
 * so sliding down the list swaps the card's contents instead of waiting again on every row.
 */
export function TodayPreviewCardProvider({ children }: { children: ReactNode }): JSX.Element {
    const [handle] = useState(() => PreviewCard.createHandle<TodayPreviewPayload>())
    const [open, setOpen] = useState(false)
    // A ref, so a hover that lands while a menu is open is refused on the same event.
    const menuOpen = useRef(false)
    const card = useMemo<TodayPreviewCard>(
        () => ({
            handle,
            setMenuOpen: (next) => {
                menuOpen.current = next
                if (next) {
                    setOpen(false)
                }
            },
        }),
        [handle]
    )

    return (
        <TodayPreviewCardContext.Provider value={card}>
            {children}
            <PreviewCard.Root handle={handle} open={open} onOpenChange={(next) => setOpen(next && !menuOpen.current)}>
                {({ payload }) =>
                    payload ? (
                        <PreviewCard.Portal>
                            {/* Centered on the row, so the path to a tall card is short from any row. */}
                            <PreviewCard.Positioner
                                data-quill
                                data-quill-portal="popover"
                                side="right"
                                align="center"
                                sideOffset={10}
                            >
                                {/* Inside the popup, not its `render`: on React 18 quill's Card takes no ref. */}
                                <PreviewCard.Popup className="outline-none">
                                    <Card size="sm" className="w-72 gap-0 border border-border py-0 shadow-md">
                                        {payload.kind === 'space' ? (
                                            <TodaySpaceHoverCard preview={payload} />
                                        ) : (
                                            <TodaySessionHoverCard preview={payload} />
                                        )}
                                    </Card>
                                </PreviewCard.Popup>
                            </PreviewCard.Positioner>
                        </PreviewCard.Portal>
                    ) : null
                }
            </PreviewCard.Root>
        </TodayPreviewCardContext.Provider>
    )
}
