import { PreviewCard } from '@base-ui/react/preview-card'
import { ReactNode, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { Card, Skeleton } from '@posthog/quill'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { cardSideForPointer, trackPointer } from './todayPointer'
import { TodayPreviewCard, TodayPreviewCardContext } from './todayPreviewCardContext'
import { TodayPreviewPayload } from './todayPreviewCards'

const TodayReportHoverCard = lazyWithRetry(() =>
    import('scenes/project-homepage/today/TodayReportHoverCard').then((m) => ({ default: m.TodayReportHoverCard }))
)
const TodayChatHoverCard = lazyWithRetry(() =>
    import('./TodayChatHoverCard').then((m) => ({ default: m.TodayChatHoverCard }))
)
const TodaySessionHoverCard = lazyWithRetry(() =>
    import('./TodaySessionHoverCard').then((m) => ({ default: m.TodaySessionHoverCard }))
)

function isInTextLink(payload: TodayPreviewPayload): boolean {
    return payload.kind === 'report' && payload.surface === 'briefing'
}

/** Beside a row, centered on it, so the path to a tall card is short from any row. On a link in the
 * home page text, above or below it on the side the pointer came from, so the card does not cover
 * the next link the pointer moves to. */
function TodayPreviewPositioner({
    payload,
    children,
}: {
    payload: TodayPreviewPayload
    children: ReactNode
}): JSX.Element {
    // Fixed per link: the direction at the moment the card moves to this link, not while the pointer rests on it.
    const textSide = useMemo(() => (isInTextLink(payload) ? cardSideForPointer() : null), [payload])
    const placement: Pick<PreviewCard.Positioner.Props, 'side' | 'align' | 'sideOffset'> = textSide
        ? { side: textSide, align: 'start', sideOffset: 6 }
        : { side: 'right', align: 'center', sideOffset: 10 }
    return (
        <PreviewCard.Positioner
            data-quill
            data-quill-portal="popover"
            // Quill's portal rule reads this token and wins over a z-index utility class.
            className="[--quill-z-popover:var(--z-popover-with-chart)]"
            {...placement}
        >
            {children}
        </PreviewCard.Positioner>
    )
}

/**
 * One hover card for every row in the sidebar, like PostHog Desktop. The rows are only triggers on a shared handle,
 * and Base UI skips the open delay when the pointer moves to another trigger of an open card,
 * so sliding down the list swaps the card's contents instead of waiting again on every row.
 */
export function TodayPreviewCardProvider({
    children,
    disabled = false,
}: {
    children: ReactNode
    disabled?: boolean
}): JSX.Element {
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
    useEffect(trackPointer, [])
    const close = useCallback(() => {
        setOpen(false)
    }, [])

    return (
        <TodayPreviewCardContext.Provider value={card}>
            {children}
            <PreviewCard.Root
                handle={handle}
                // A session dialog or the bulk archive confirm keeps the card shut, so the card cannot open over it.
                open={open && !disabled}
                onOpenChange={(next) => setOpen(next && !menuOpen.current && !disabled)}
            >
                {({ payload }) =>
                    payload ? (
                        <PreviewCard.Portal>
                            <TodayPreviewPositioner payload={payload}>
                                {/* Inside the popup, not its `render`: on React 18 quill's Card takes no ref. */}
                                <PreviewCard.Popup className="outline-none">
                                    <Card
                                        size="sm"
                                        className="w-72 gap-0 border border-border py-0 shadow-[var(--shadow-md)]"
                                    >
                                        <Suspense fallback={<Skeleton className="h-24 w-full" />}>
                                            {payload.kind === 'chat' ? (
                                                <TodayChatHoverCard preview={payload} onAction={close} />
                                            ) : payload.kind === 'report' ? (
                                                <TodayReportHoverCard preview={payload} />
                                            ) : (
                                                <TodaySessionHoverCard preview={payload} onAction={close} />
                                            )}
                                        </Suspense>
                                    </Card>
                                </PreviewCard.Popup>
                            </TodayPreviewPositioner>
                        </PreviewCard.Portal>
                    ) : null
                }
            </PreviewCard.Root>
        </TodayPreviewCardContext.Provider>
    )
}
