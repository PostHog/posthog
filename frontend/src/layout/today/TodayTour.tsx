import { useValues } from 'kea'
import { useRef } from 'react'

import { TodayTourCard } from './TodayTourCard'
import { TodayTourCursor } from './TodayTourCursor'
import { todayTourLogic } from './todayTourLogic'

/** The tour while it runs: the cursor that moves between steps, and the card for a step once the cursor stopped. */
export function TodayTour(): JSX.Element | null {
    const { tour, tourStep } = useValues(todayTourLogic)
    const refocusNextRef = useRef(false)

    if (!tour || !tourStep) {
        return null
    }

    return (
        <>
            {/* Not keyed, so it stays mounted across steps and moves on from where it stopped. */}
            <TodayTourCursor />
            {tour.anchor && (
                // Keyed by step, so each step starts with a fresh card: its own entrance, timer and hover state.
                <TodayTourCard
                    key={tour.stepIndex}
                    step={tourStep}
                    stepIndex={tour.stepIndex}
                    anchor={tour.anchor}
                    refocusNextRef={refocusNextRef}
                />
            )}
        </>
    )
}
