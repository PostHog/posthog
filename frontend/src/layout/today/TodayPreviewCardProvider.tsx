import { PreviewCard } from '@base-ui/react/preview-card'
import { ReactNode, Suspense, useCallback, useMemo, useRef, useState } from 'react'

import { Card, Skeleton } from '@posthog/quill'

import { lazyWithRetry } from 'lib/utils/retryImport'

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
const TodaySpaceHoverCard = lazyWithRetry(() =>
    import('./TodaySpaceHoverCard').then((m) => ({ default: m.TodaySpaceHoverCard }))
)

/** Beside a row, centered on it, so the path to a tall card is short from any row. Under a link in the
 * briefing text instead, so the card does not cover the line. */
function placement(payload: TodayPreviewPayload): Pick<PreviewCard.Positioner.Props, 'side' | 'align' | 'sideOffset'> {
    return payload.kind === 'report' && payload.surface === 'briefing'
        ? { side: 'bottom', align: 'start', sideOffset: 6 }
        : { side: 'right', align: 'center', sideOffset: 10 }
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
    // "File to…" opens outside the card, so the pointer moving there reads as leaving it.
    const [submenuOpen, setSubmenuOpen] = useState(false)
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
        setSubmenuOpen(false)
        setOpen(false)
    }, [])

    return (
        <TodayPreviewCardContext.Provider value={card}>
            {children}
            <PreviewCard.Root
                handle={handle}
                // A session dialog or the bulk archive confirm keeps the card shut, so the card cannot open over it.
                open={(open || submenuOpen) && !disabled}
                onOpenChange={(next) => setOpen(next && !menuOpen.current && !disabled)}
            >
                {({ payload }) =>
                    payload ? (
                        <PreviewCard.Portal>
                            <PreviewCard.Positioner
                                data-quill
                                data-quill-portal="popover"
                                // Quill's portal rule reads this token and wins over a z-index utility class.
                                className="[--quill-z-popover:var(--z-popover-with-chart)]"
                                {...placement(payload)}
                            >
                                {/* Inside the popup, not its `render`: on React 18 quill's Card takes no ref. */}
                                <PreviewCard.Popup className="outline-none">
                                    <Card
                                        size="sm"
                                        className="w-72 gap-0 border border-border py-0 shadow-[var(--shadow-md)]"
                                    >
                                        <Suspense fallback={<Skeleton className="h-24 w-full" />}>
                                            {payload.kind === 'space' ? (
                                                <TodaySpaceHoverCard preview={payload} onAction={close} />
                                            ) : payload.kind === 'chat' ? (
                                                <TodayChatHoverCard preview={payload} onAction={close} />
                                            ) : payload.kind === 'report' ? (
                                                <TodayReportHoverCard preview={payload} />
                                            ) : (
                                                <TodaySessionHoverCard
                                                    // Keyed on the row, so moving to another row unmounts the card and lowers the submenu flag.
                                                    key={payload.menu.menuId}
                                                    preview={payload}
                                                    onAction={close}
                                                    onSubmenuOpenChange={setSubmenuOpen}
                                                />
                                            )}
                                        </Suspense>
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
