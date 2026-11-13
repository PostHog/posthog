import { useActions, useValues } from 'kea'
import { useEffect, useLayoutEffect, useRef } from 'react'

import { useReducedMotion } from '@posthog/quill'

import { TodayTourPoint, centerOf } from './todayTourGeometry'
import { TodayTourStep, todayTourLogic } from './todayTourLogic'

// pinned: the data-attrs of the rail tiles (TodayRail), the "More" tile and its switch item (TodayMoreMenu).
const MORE_TILE = '[data-attr="help-menu-button"]'
const NAV_SWITCH_ITEM = '[data-attr="more-menu-nav-switch-button"]'
const SIDEBAR = '.TodayShell__sidebar'

// The cursor art's own colors, not theme tokens: it is an illustration and looks the same in both themes.
const CURSOR_INK = '#6b44bc'
const CURSOR_PAPER = '#f8f7f2'

const EASE_OUT_QUINT = 'cubic-bezier(0.23, 1, 0.32, 1)'
// The two axes ease differently, so the cursor travels on a slight arc, the way a hand moves a mouse.
const TRAVEL_EASE_X = 'cubic-bezier(0.55, 0, 0.25, 1)'
const TRAVEL_EASE_Y = 'cubic-bezier(0.3, 0, 0.15, 1)'
// Lets the "PostHog is changing" dialog start closing before the cursor leaves the button it clicked.
const START_DELAY_MS = 250
// Lets the page the click opened render before the cursor measures where to go next.
const SETTLE_MS = 350
const FIND_TIMEOUT_MS = 1500
const PRESS_MS = 260
const PRESS_DOWN_MS = 90
// The cursor rests this far inside the right edge of what it points at, so the card beside it clears that element.
const REST_INSET_PX = 20

function travelMs(from: TodayTourPoint, to: TodayTourPoint): number {
    return Math.min(900, Math.max(400, 250 + Math.hypot(to.x - from.x, to.y - from.y) * 0.6))
}

function targetSelector(step: TodayTourStep): string {
    return step.kind === 'switch' ? MORE_TILE : `[data-attr="today-rail-${step.pane}"]`
}

/** What the cursor rests on while the card shows. `null` is the middle of the page. */
function restSelector(step: TodayTourStep): string | null {
    if (step.kind === 'switch') {
        return NAV_SWITCH_ITEM
    }
    return step.pointsAt === 'sidebar' ? SIDEBAR : null
}

function pageCenter(): TodayTourPoint {
    const main = document.getElementById('main-content')
    return main ? centerOf(main) : { x: window.innerWidth / 2, y: window.innerHeight / 2 }
}

/**
 * The steps of one cursor run. Each wait rejects once the run is aborted, even a wait that already finished, so the run
 * stops at its next `await` and never acts for a step that has moved on.
 */
function cursorRun(
    signal: AbortSignal,
    reducedMotion: boolean
): {
    play: (element: HTMLElement | null, keyframes: Keyframe[], options: KeyframeAnimationOptions) => Promise<void>
    sleep: (ms: number) => Promise<void>
    findElement: (selector: string) => Promise<HTMLElement | null>
} {
    const checked = <T,>(promise: Promise<T>): Promise<T> =>
        promise.then((value) => {
            signal.throwIfAborted()
            return value
        })

    const sleep = (ms: number): Promise<void> =>
        checked(
            new Promise((resolve, reject) => {
                const timeout = window.setTimeout(resolve, reducedMotion ? 0 : ms)
                signal.addEventListener(
                    'abort',
                    () => {
                        window.clearTimeout(timeout)
                        reject(signal.reason)
                    },
                    { once: true }
                )
            })
        )

    const play = (
        element: HTMLElement | null,
        keyframes: Keyframe[],
        options: KeyframeAnimationOptions
    ): Promise<void> => {
        if (!element || reducedMotion) {
            return checked(Promise.resolve())
        }
        const animation = element.animate(keyframes, options)
        signal.addEventListener('abort', () => animation.cancel(), { once: true })
        return checked(animation.finished.then(() => undefined))
    }

    // The menu renders in a portal a frame or more after it opens, so poll until the element has a box.
    const findElement = async (selector: string): Promise<HTMLElement | null> => {
        const deadline = performance.now() + FIND_TIMEOUT_MS
        while (performance.now() < deadline) {
            const element = document.querySelector<HTMLElement>(selector)
            if (element && element.getBoundingClientRect().width > 0) {
                return element
            }
            await checked(new Promise((resolve) => requestAnimationFrame(resolve)))
        }
        return null
    }

    return { play, sleep, findElement }
}

/**
 * A pretend cursor that shows each step of the tour: it moves to the step's rail tile, clicks it, then moves to
 * where the card should show. It is decoration only, so it ignores the pointer and is hidden from assistive tech.
 */
export function TodayTourCursor(): JSX.Element {
    const { tour, tourStep } = useValues(todayTourLogic)
    const { clickTourTarget, revealTourStep, endTour } = useActions(todayTourLogic)
    const reducedMotion = useReducedMotion()
    const xRef = useRef<HTMLDivElement>(null)
    const yRef = useRef<HTMLDivElement>(null)
    const pressRef = useRef<HTMLDivElement>(null)
    const rippleRef = useRef<HTMLDivElement>(null)
    const positionRef = useRef<TodayTourPoint>(tour?.origin ?? pageCenter())
    const stepIndex = tour?.stepIndex ?? null

    useLayoutEffect(() => {
        const { x, y } = positionRef.current
        xRef.current?.style.setProperty('transform', `translateX(${x}px)`)
        yRef.current?.style.setProperty('transform', `translateY(${y}px)`)
        if (!reducedMotion) {
            pressRef.current?.animate(
                [
                    { opacity: 0, transform: 'scale(0.6)' },
                    { opacity: 1, transform: 'none' },
                ],
                { duration: 200, easing: EASE_OUT_QUINT }
            )
        }
    }, [reducedMotion])

    useEffect(() => {
        if (!tourStep || stepIndex === null) {
            return
        }
        const controller = new AbortController()
        const { play, sleep, findElement } = cursorRun(controller.signal, reducedMotion)

        // The resting transform is written first, so the cursor stays put when the animation ends or is cancelled.
        const moveTo = async (to: TodayTourPoint): Promise<void> => {
            const from = positionRef.current
            positionRef.current = to
            xRef.current?.style.setProperty('transform', `translateX(${to.x}px)`)
            yRef.current?.style.setProperty('transform', `translateY(${to.y}px)`)
            const duration = travelMs(from, to)
            await Promise.all([
                play(xRef.current, [{ transform: `translateX(${from.x}px)` }, { transform: `translateX(${to.x}px)` }], {
                    duration,
                    easing: TRAVEL_EASE_X,
                }),
                play(yRef.current, [{ transform: `translateY(${from.y}px)` }, { transform: `translateY(${to.y}px)` }], {
                    duration,
                    easing: TRAVEL_EASE_Y,
                }),
            ])
        }

        // The click lands at the bottom of the press, where the ripple starts.
        const click = async (): Promise<void> => {
            const press = play(
                pressRef.current,
                [
                    { transform: 'none', easing: 'ease-out' },
                    { transform: 'scale(0.82)', offset: PRESS_DOWN_MS / PRESS_MS, easing: EASE_OUT_QUINT },
                    { transform: 'none' },
                ],
                { duration: PRESS_MS }
            )
            await sleep(PRESS_DOWN_MS)
            clickTourTarget()
            void play(
                rippleRef.current,
                [
                    { opacity: 0.45, transform: 'translate(-50%, -50%) scale(0.2)' },
                    { opacity: 0, transform: 'translate(-50%, -50%) scale(1)' },
                ],
                { duration: 550, easing: EASE_OUT_QUINT }
                // Nothing waits for the ripple. It only rejects when the run is aborted.
            ).catch(() => {})
            await press
        }

        const run = async (): Promise<void> => {
            if (stepIndex === 0) {
                await sleep(START_DELAY_MS)
            }
            const target = document.querySelector(targetSelector(tourStep))
            if (target) {
                await moveTo(centerOf(target))
                await click()
            } else {
                clickTourTarget()
            }
            await sleep(SETTLE_MS)
            const selector = restSelector(tourStep)
            const restOn = selector ? await findElement(selector) : null
            let rest = pageCenter()
            if (restOn) {
                const rect = restOn.getBoundingClientRect()
                rest = { x: rect.right - REST_INSET_PX, y: rect.top + Math.min(rect.height / 2, 200) }
            }
            await moveTo(rest)
            if (tourStep.kind === 'switch') {
                // Focus is how a menu marks the row under the pointer, so the item lights up as if hovered.
                restOn?.focus({ preventScroll: true })
            }
            revealTourStep(rest)
        }

        run().catch((error: unknown) => {
            // An abort is the step moving on or the tour ending. Anything else would leave the tour with no card
            // and no way out, so end it and let the error reach error tracking.
            if (!controller.signal.aborted) {
                endTour()
                throw error
            }
        })
        return () => controller.abort()
    }, [tourStep, stepIndex, reducedMotion, clickTourTarget, revealTourStep, endTour])

    return (
        <div ref={xRef} aria-hidden className="pointer-events-none fixed top-0 left-0 z-[var(--z-tooltip)]">
            <div ref={yRef}>
                <div
                    ref={rippleRef}
                    className="absolute top-0 left-0 size-12 rounded-full opacity-0"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ backgroundColor: CURSOR_INK }}
                />
                <div ref={pressRef} className="origin-top-left">
                    {/* The arrow's tip is the click point, at the origin. The solid copy behind it gives it depth. */}
                    <svg
                        viewBox="-4 -1.5 22 20"
                        width="28"
                        height="25"
                        className="absolute top-[-2px] left-[-5px] drop-shadow-sm"
                    >
                        <path
                            d="M-3 1.5 L11 6 L6.8 8.5 L13 14.7 L10.2 17.5 L4 11.3 L1.5 15.5 Z"
                            fill={CURSOR_INK}
                            stroke={CURSOR_INK}
                            strokeWidth="1.4"
                            strokeLinejoin="round"
                        />
                        <path
                            d="M0 0 L14 4.5 L9.8 7 L16 13.2 L13.2 16 L7 9.8 L4.5 14 Z"
                            fill={CURSOR_PAPER}
                            stroke={CURSOR_INK}
                            strokeWidth="1.4"
                            strokeLinejoin="round"
                        />
                    </svg>
                </div>
            </div>
        </div>
    )
}
