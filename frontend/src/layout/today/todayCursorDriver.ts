import { MutableRefObject, RefObject, createRef, useRef } from 'react'

import { TodayTourPoint } from './todayTourGeometry'

const CURSOR_EASE_OUT_QUINT = 'cubic-bezier(0.23, 1, 0.32, 1)'
// The two axes ease differently, so the cursor travels on a slight arc, the way a hand moves a mouse.
const TRAVEL_EASE_X = 'cubic-bezier(0.55, 0, 0.25, 1)'
const TRAVEL_EASE_Y = 'cubic-bezier(0.3, 0, 0.15, 1)'
const FIND_TIMEOUT_MS = 1500
const PRESS_MS = 260
const PRESS_DOWN_MS = 90

function travelMs(from: TodayTourPoint, to: TodayTourPoint): number {
    return Math.min(900, Math.max(400, 250 + Math.hypot(to.x - from.x, to.y - from.y) * 0.6))
}

/** The parts of the pretend cursor a run animates. `TodayCursorArt` renders them. */
export interface TodayCursorRefs {
    x: RefObject<HTMLDivElement>
    y: RefObject<HTMLDivElement>
    press: RefObject<HTMLDivElement>
    ripple: RefObject<HTMLDivElement>
    /** Where the cursor rests now, so the next move starts from there. */
    position: MutableRefObject<TodayTourPoint>
}

export interface TodayCursorRun {
    sleep: (ms: number) => Promise<void>
    /** The element once it has a box. Menus render in a portal a frame or more after they open, so it polls. */
    findElement: (selector: string) => Promise<HTMLElement | null>
    moveTo: (to: TodayTourPoint) => Promise<void>
    /** Presses the cursor down, calls `onPress` at the bottom of the press, and ripples from there. */
    click: (onPress: () => void) => Promise<void>
}

/** The cursor's refs, created once, so a run started in an effect keeps pointing at the same elements. */
export function useTodayCursorRefs(origin: TodayTourPoint): TodayCursorRefs {
    const refs = useRef<TodayCursorRefs | null>(null)
    if (!refs.current) {
        refs.current = {
            x: createRef<HTMLDivElement>(),
            y: createRef<HTMLDivElement>(),
            press: createRef<HTMLDivElement>(),
            ripple: createRef<HTMLDivElement>(),
            position: { current: origin },
        }
    }
    return refs.current
}

/** Puts the cursor at `point` at once, so the next move starts from there. */
function placeTodayCursor(refs: TodayCursorRefs, point: TodayTourPoint): void {
    refs.position.current = point
    refs.x.current?.style.setProperty('transform', `translateX(${point.x}px)`)
    refs.y.current?.style.setProperty('transform', `translateY(${point.y}px)`)
}

/** Shows the cursor at `point`, popping in unless motion is reduced. */
export function enterTodayCursor(refs: TodayCursorRefs, point: TodayTourPoint, reducedMotion: boolean): void {
    placeTodayCursor(refs, point)
    if (!reducedMotion) {
        refs.press.current?.animate(
            [
                { opacity: 0, transform: 'scale(0.6)' },
                { opacity: 1, transform: 'none' },
            ],
            { duration: 200, easing: CURSOR_EASE_OUT_QUINT }
        )
    }
}

/**
 * One run of the pretend cursor. Each wait rejects once the run is aborted, even a wait that already finished, so the
 * run stops at its next `await` and never acts for a run that has moved on.
 */
export function todayCursorRun(signal: AbortSignal, reducedMotion: boolean, refs: TodayCursorRefs): TodayCursorRun {
    const checked = <T>(promise: Promise<T>): Promise<T> =>
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

    // The resting transform is written first, so the cursor stays put when the animation ends or is cancelled.
    const moveTo = async (to: TodayTourPoint): Promise<void> => {
        const from = refs.position.current
        placeTodayCursor(refs, to)
        const duration = travelMs(from, to)
        await Promise.all([
            play(refs.x.current, [{ transform: `translateX(${from.x}px)` }, { transform: `translateX(${to.x}px)` }], {
                duration,
                easing: TRAVEL_EASE_X,
            }),
            play(refs.y.current, [{ transform: `translateY(${from.y}px)` }, { transform: `translateY(${to.y}px)` }], {
                duration,
                easing: TRAVEL_EASE_Y,
            }),
        ])
    }

    const click = async (onPress: () => void): Promise<void> => {
        const press = play(
            refs.press.current,
            [
                { transform: 'none', easing: 'ease-out' },
                { transform: 'scale(0.82)', offset: PRESS_DOWN_MS / PRESS_MS, easing: CURSOR_EASE_OUT_QUINT },
                { transform: 'none' },
            ],
            { duration: PRESS_MS }
        )
        await sleep(PRESS_DOWN_MS)
        onPress()
        void play(
            refs.ripple.current,
            [
                { opacity: 0.45, transform: 'translate(-50%, -50%) scale(0.2)' },
                { opacity: 0, transform: 'translate(-50%, -50%) scale(1)' },
            ],
            { duration: 550, easing: CURSOR_EASE_OUT_QUINT }
            // Nothing waits for the ripple. It only rejects when the run is aborted.
        ).catch(() => {})
        await press
    }

    return { sleep, findElement, moveTo, click }
}
