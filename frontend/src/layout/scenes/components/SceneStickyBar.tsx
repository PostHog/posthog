import { RefObject, forwardRef, useEffect, useState } from 'react'

import { cn } from 'lib/utils/css-classes'

interface SceneStickyBarProps {
    children: React.ReactNode
    className?: string
    showBorderBottom?: boolean
    hasSceneTitleSection?: boolean
}

export const SceneStickyBar = forwardRef<HTMLDivElement, SceneStickyBarProps>(function SceneStickyBar(
    { children, className, showBorderBottom = true, hasSceneTitleSection = true },
    ref
): JSX.Element {
    return (
        <div
            ref={ref}
            className={cn(
                'scene-sticky-bar @2xl/main-content:sticky z-20 bg-primary @2xl/main-content:top-[34px] space-y-2 py-2 -mx-4 px-4 rounded-t-xl',
                // Without a scene title section the bar pins itself. Sticky offsets start inside the
                // scroll container's padding, so pull it up by that padding to stop content showing above.
                !hasSceneTitleSection && '@2xl/main-content:-top-4',
                className,
                showBorderBottom && 'border-b'
            )}
        >
            {children}
        </div>
    )
})

/**
 * Returns the sticky offset, in pixels, of the bottom edge of a pinned `SceneStickyBar`: its `top` plus its height.
 * Use it to pin other sticky content (for example a `LemonTable` with `stickyHeader`) directly below the bar.
 * The value updates when the bar changes size (for example when its filters wrap) or when the scene resizes.
 */
export function useSceneStickyBarBottom(barRef: RefObject<HTMLElement>): number {
    const [bottom, setBottom] = useState(0)

    useEffect(() => {
        const bar = barRef.current
        if (!bar || typeof ResizeObserver === 'undefined') {
            return
        }
        const update = (): void => {
            // `top` is only set from the breakpoint where the bar is sticky. Below it, `top` is `auto`.
            const top = parseFloat(getComputedStyle(bar).top)
            setBottom((Number.isNaN(top) ? 0 : top) + bar.offsetHeight)
        }
        const observer = new ResizeObserver(update)
        observer.observe(bar)
        // The bar's `top` changes at a container breakpoint, which can occur without a change to the bar's size.
        // The parent's size changes when the scene crosses that breakpoint, so observe it too.
        if (bar.parentElement) {
            observer.observe(bar.parentElement)
        }
        update()
        return () => observer.disconnect()
    }, [barRef])

    return bottom
}
