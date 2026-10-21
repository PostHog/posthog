import { PreviewCard } from '@base-ui/react/preview-card'
import { ReactNode, Suspense, useCallback, useMemo, useRef, useState } from 'react'

import { Card, Skeleton } from '@posthog/quill'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { TodayPreviewCard, TodayPreviewCardContext } from './todayPreviewCardContext'
import { TodayPreviewPayload } from './todayPreviewCards'

const TodayChatHoverCard = lazyWithRetry(() =>
    import('./TodayChatHoverCard').then((m) => ({ default: m.TodayChatHoverCard }))
)
const TodayObjectHoverCard = lazyWithRetry(() =>
    import('./TodayObjectHoverCard').then((m) => ({ default: m.TodayObjectHoverCard }))
)
const TodayProductHoverCard = lazyWithRetry(() =>
    import('./TodayProductHoverCard').then((m) => ({ default: m.TodayProductHoverCard }))
)
const TodaySessionHoverCard = lazyWithRetry(() =>
    import('./TodaySessionHoverCard').then((m) => ({ default: m.TodaySessionHoverCard }))
)

function TodayPreviewPositioner({ below, children }: { below: boolean; children: ReactNode }): JSX.Element {
    return (
        <PreviewCard.Positioner
            data-quill
            data-quill-portal="popover"
            // Quill's portal rule reads this token and wins over a z-index utility class.
            className="[--quill-z-popover:var(--z-popover-with-chart)]"
            side={below ? 'bottom' : 'right'}
            align={below ? 'start' : 'center'}
            sideOffset={below ? 6 : 10}
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
                            <TodayPreviewPositioner below={payload.kind === 'object'}>
                                {/* Inside the popup, not its `render`: on React 18 quill's Card takes no ref. */}
                                <PreviewCard.Popup className="origin-[var(--transform-origin)] outline-none transition-[opacity,scale] duration-150 ease-out data-[ending-style]:scale-97 data-[ending-style]:opacity-0 data-[starting-style]:scale-97 data-[starting-style]:opacity-0 motion-reduce:transition-none">
                                    <Card
                                        size="sm"
                                        className="w-72 gap-0 border border-border py-0 shadow-[var(--shadow-md)]"
                                    >
                                        <Suspense fallback={<Skeleton className="h-24 w-full" />}>
                                            {payload.kind === 'chat' ? (
                                                <TodayChatHoverCard preview={payload} onAction={close} />
                                            ) : payload.kind === 'object' ? (
                                                <TodayObjectHoverCard preview={payload} onAction={close} />
                                            ) : payload.kind === 'product' ? (
                                                <TodayProductHoverCard preview={payload} onAction={close} />
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
