import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'

import type { WoWChangeApi } from 'products/web_analytics/frontend/generated/api.schemas'

function prefersReducedMotion(): boolean {
    return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

function useInView<T extends HTMLElement>(threshold = 0.25): [React.RefObject<T>, boolean] {
    const ref = useRef<T>(null)
    const [inView, setInView] = useState(false)

    useEffect(() => {
        const node = ref.current
        if (!node) {
            return
        }
        if (prefersReducedMotion() || typeof IntersectionObserver === 'undefined') {
            setInView(true)
            return
        }
        const observer = new IntersectionObserver(
            ([entry]) => {
                if (entry.isIntersecting) {
                    setInView(true)
                    observer.disconnect()
                }
            },
            { threshold }
        )
        observer.observe(node)
        return () => observer.disconnect()
    }, [threshold])

    return [ref, inView]
}

/** Fades and slides children up the first time they scroll into view. Honors prefers-reduced-motion. */
export function Reveal({
    children,
    className,
    delayMs = 0,
    onInView,
}: {
    children: React.ReactNode
    className?: string
    delayMs?: number
    onInView?: () => void
}): JSX.Element {
    const [ref, inView] = useInView<HTMLDivElement>()
    useEffect(() => {
        if (inView) {
            onInView?.()
        }
        // onInView is intentionally not a dep — fire once when the section first enters view
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [inView])
    return (
        <div
            ref={ref}
            className={clsx(
                'transition-all duration-700 ease-out motion-reduce:transition-none',
                inView ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8',
                className
            )}
            style={{ transitionDelay: `${delayMs}ms` }}
        >
            {children}
        </div>
    )
}

/** Counts a number up from zero the first time it scrolls into view. */
export function CountUp({
    value,
    durationMs = 1400,
    className,
    suffix = '',
}: {
    value: number
    durationMs?: number
    className?: string
    suffix?: string
}): JSX.Element {
    const [ref, inView] = useInView<HTMLSpanElement>()
    const [display, setDisplay] = useState(0)

    useEffect(() => {
        if (!inView) {
            return
        }
        if (prefersReducedMotion()) {
            setDisplay(value)
            return
        }
        let raf = 0
        let start: number | null = null
        const tick = (now: number): void => {
            start ??= now
            const progress = Math.min((now - start) / durationMs, 1)
            // easeOutCubic for a satisfying deceleration
            const eased = 1 - Math.pow(1 - progress, 3)
            setDisplay(value * eased)
            if (progress < 1) {
                raf = requestAnimationFrame(tick)
            }
        }
        raf = requestAnimationFrame(tick)
        return () => cancelAnimationFrame(raf)
    }, [inView, value, durationMs])

    return (
        <span ref={ref} className={clsx('tabular-nums', className)}>
            {Math.round(display).toLocaleString()}
            {suffix}
        </span>
    )
}

/** Small up/down pill colored by the backend's good/bad signal. */
export function TrendPill({
    change,
    className,
}: {
    change: WoWChangeApi | null
    className?: string
}): JSX.Element | null {
    if (!change) {
        return null
    }
    return (
        <span
            className={clsx('inline-flex items-center gap-0.5 text-sm font-semibold', className)}
            style={{ color: change.color }}
            title={change.long_text}
        >
            <span className="leading-none">{change.direction === 'Up' ? '↑' : '↓'}</span>
            {change.percent}%
        </span>
    )
}

/** A decorative "scroll down to continue" affordance. Hidden entirely for reduced-motion users. */
export function ScrollHint({
    label = 'Scroll to continue',
    className,
}: {
    label?: string
    className?: string
}): JSX.Element | null {
    if (prefersReducedMotion()) {
        return null
    }
    return (
        <div
            aria-hidden
            className={clsx(
                'pointer-events-none flex flex-col items-center gap-1 text-secondary select-none',
                className
            )}
        >
            <span className="text-xs uppercase tracking-widest opacity-70">{label}</span>
            <IconChevronDown className="text-2xl animate-bounce" />
        </div>
    )
}
