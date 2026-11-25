import { RefObject, useEffect, useRef } from 'react'

import { TODAY_RAIL_PANES, TodayRailPane } from './todayShellLogic'

const RAIL_ORDER: TodayRailPane[] = [...TODAY_RAIL_PANES, 'settings']

// Small and soft: the rail is used all day, so the motion only hints at the direction of travel.
const PANE_OFFSET_PX = 4
const PANE_DURATION_MS = 220
const PAGE_DURATION_MS = 220
// The pane moves first and the page follows, so the eye goes to the nav before the content.
const PAGE_DELAY_MS = 40
// Fades start part of the way in, so a swap dims rather than blanks.
const PANE_START_OPACITY = 0.4
const PAGE_START_OPACITY = 0.5
// An ease-out cubic: it settles gradually, where a steeper curve lands all at once and reads as a jolt.
const EASE_OUT = 'cubic-bezier(0.215, 0.61, 0.355, 1)'

export function paneTransitionDirection(previous: TodayRailPane, next: TodayRailPane): -1 | 0 | 1 {
    const delta = RAIL_ORDER.indexOf(next) - RAIL_ORDER.indexOf(previous)
    return delta === 0 ? 0 : delta > 0 ? 1 : -1
}

export function useTodayPaneTransition(
    activePane: TodayRailPane,
    paneRef: RefObject<HTMLElement>,
    { animatePane }: { animatePane: boolean }
): void {
    const previousPane = useRef(activePane)

    useEffect(() => {
        const direction = paneTransitionDirection(previousPane.current, activePane)
        previousPane.current = activePane
        if (direction === 0 || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
            return
        }
        const page = document.getElementById('main-content')
        // Test environments have no Web Animations API.
        if (typeof page?.animate !== 'function') {
            return
        }
        if (animatePane) {
            paneRef.current?.animate(
                [
                    { opacity: PANE_START_OPACITY, transform: `translateY(${direction * PANE_OFFSET_PX}px)` },
                    { opacity: 1, transform: 'none' },
                ],
                { duration: PANE_DURATION_MS, easing: EASE_OUT }
            )
        }
        page.animate([{ opacity: PAGE_START_OPACITY }, { opacity: 1 }], {
            duration: PAGE_DURATION_MS,
            delay: PAGE_DELAY_MS,
            easing: EASE_OUT,
            // Holds the page dimmed through the delay, so it doesn't flash bright before the fade.
            fill: 'backwards',
        })
    }, [activePane, animatePane, paneRef])
}
