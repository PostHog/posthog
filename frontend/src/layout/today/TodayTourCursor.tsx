import { useActions, useValues } from 'kea'
import { useEffect, useLayoutEffect } from 'react'

import { useReducedMotion } from '@posthog/quill'

import { TodayCursorArt } from './TodayCursorArt'
import { enterTodayCursor, todayCursorRun, useTodayCursorRefs } from './todayCursorDriver'
import { TodayTourPoint, centerOf } from './todayTourGeometry'
import { TodayTourStep, todayTourLogic } from './todayTourLogic'

const SIDEBAR = '.TodayShell__sidebar'

// Lets the "PostHog is changing" dialog start closing before the cursor leaves the button it clicked.
const START_DELAY_MS = 250
// Lets the page the click opened render before the cursor measures where to go next.
const SETTLE_MS = 350
// The cursor rests this far inside the right edge of what it points at, so the card beside it clears that element.
const REST_INSET_PX = 20

function targetSelector(step: TodayTourStep): string {
    if (step.pane === 'settings') {
        return '[data-attr="new-account-menu-button"]'
    }
    return `[data-attr="today-rail-${step.pane}"]`
}

/** What the cursor rests on while the card shows, in order of preference. None is the middle of the page. */
function restSelectors(step: TodayTourStep): string[] {
    if (step.pointsAt === 'intro') {
        // The pane header can still be loading, so the sidebar is the fallback.
        return [`[data-attr="today-pane-intro-${step.pane}"]`, SIDEBAR]
    }
    return step.pointsAt === 'sidebar' ? [SIDEBAR] : []
}

function pageCenter(): TodayTourPoint {
    const main = document.getElementById('main-content')
    return main ? centerOf(main) : { x: window.innerWidth / 2, y: window.innerHeight / 2 }
}

/**
 * A pretend cursor that shows each step of the tour: it moves to the step's rail tile, clicks it, then moves to
 * where the card should show. It is decoration only, so it ignores the pointer and is hidden from assistive tech.
 */
export function TodayTourCursor(): JSX.Element {
    const { tour, tourStep } = useValues(todayTourLogic)
    const { clickTourTarget, revealTourStep, endTour } = useActions(todayTourLogic)
    const reducedMotion = useReducedMotion()
    const refs = useTodayCursorRefs(tour?.origin ?? pageCenter())
    const stepIndex = tour?.stepIndex ?? null

    useLayoutEffect(() => {
        enterTodayCursor(refs, refs.position.current, reducedMotion)
    }, [reducedMotion, refs])

    useEffect(() => {
        if (!tourStep || stepIndex === null) {
            return
        }
        const controller = new AbortController()
        const { sleep, findElement, moveTo, click } = todayCursorRun(controller.signal, reducedMotion, refs)

        const run = async (): Promise<void> => {
            if (stepIndex === 0) {
                await sleep(START_DELAY_MS)
            }
            const target = document.querySelector(targetSelector(tourStep))
            if (target) {
                await moveTo(centerOf(target))
                await click(clickTourTarget)
            } else {
                clickTourTarget()
            }
            await sleep(SETTLE_MS)
            let restOn: HTMLElement | null = null
            for (const selector of restSelectors(tourStep)) {
                restOn = await findElement(selector)
                if (restOn) {
                    break
                }
            }
            let rest = pageCenter()
            if (restOn) {
                const rect = restOn.getBoundingClientRect()
                rest = { x: rect.right - REST_INSET_PX, y: rect.top + Math.min(rect.height / 2, 200) }
            }
            await moveTo(rest)
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
    }, [tourStep, stepIndex, reducedMotion, refs, clickTourTarget, revealTourStep, endTour])

    return <TodayCursorArt refs={refs} />
}
