import { useEffect, useRef, useState } from 'react'

import { cn } from '@posthog/quill'

const TICKER_SPEED_PX_PER_SECOND = 50
const TICKER_FADE_PX = 24
/** A title that overflows by a character or two keeps its fade: moving costs more to read than the glyphs are worth. */
const TICKER_MIN_OVERFLOW_PX = 12

function tickerMask(overflowPx: number, isTicking: boolean, showsEnd: boolean): string | undefined {
    if (overflowPx === 0) {
        return undefined
    }
    const fadeIn = `transparent, black ${TICKER_FADE_PX}px`
    const fadeOut = `black calc(100% - ${TICKER_FADE_PX}px), transparent`
    if (!isTicking) {
        return `linear-gradient(to right, ${fadeOut})`
    }
    if (showsEnd) {
        return `linear-gradient(to right, ${fadeIn})`
    }
    return `linear-gradient(to right, ${fadeIn}, ${fadeOut})`
}

function prefersReducedMotion(): boolean {
    return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

/** Fades a title that does not fit, and scrolls it to its end while `reveal` is on, like the desktop work column. */
export function TodayOverflowText({
    reveal,
    className,
    children,
}: {
    reveal: boolean
    className?: string
    children: React.ReactNode
}): JSX.Element {
    const containerRef = useRef<HTMLSpanElement>(null)
    const contentRef = useRef<HTMLSpanElement>(null)
    const [overflowPx, setOverflowPx] = useState(0)
    const [reachedEnd, setReachedEnd] = useState(false)

    useEffect(() => {
        if (!reveal) {
            setReachedEnd(false)
        }
    }, [reveal])

    useEffect(() => {
        setReachedEnd(false)
    }, [overflowPx])

    useEffect(() => {
        const container = containerRef.current
        const content = contentRef.current
        if (!container || !content) {
            return
        }
        const measure = (): void => setOverflowPx(Math.max(0, container.scrollWidth - container.clientWidth))
        measure()
        const observer = new ResizeObserver(measure)
        observer.observe(container)
        observer.observe(content)
        return () => observer.disconnect()
    }, [])

    const reducedMotion = prefersReducedMotion()
    const isTicking = reveal && overflowPx >= TICKER_MIN_OVERFLOW_PX
    const maskImage = tickerMask(overflowPx, isTicking, reachedEnd || (isTicking && reducedMotion))

    return (
        <span
            ref={containerRef}
            className={cn('min-w-0 overflow-hidden whitespace-nowrap', className)}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ maskImage, WebkitMaskImage: maskImage }}
        >
            <span
                ref={contentRef}
                className="inline-block"
                onTransitionEnd={(e) => {
                    if (e.target === e.currentTarget && e.propertyName === 'transform') {
                        setReachedEnd(true)
                    }
                }}
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    isTicking
                        ? {
                              transform: `translateX(-${overflowPx}px)`,
                              transitionProperty: reducedMotion ? 'none' : 'transform',
                              transitionTimingFunction: 'linear',
                              transitionDuration: `${overflowPx / TICKER_SPEED_PX_PER_SECOND}s`,
                          }
                        : { transform: 'translateX(0)', transitionProperty: 'none' }
                }
            >
                {children}
            </span>
        </span>
    )
}
