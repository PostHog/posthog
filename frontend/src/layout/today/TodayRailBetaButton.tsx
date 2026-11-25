import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { Badge, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { clickPoint } from './todayTourGeometry'
import { todayTourLogic } from './todayTourLogic'

/** Marks the new navigation as a beta on the rail, and starts the design tour again. */
export function TodayRailBetaButton(): JSX.Element {
    const { tourActive } = useValues(todayTourLogic)
    const { startTour } = useActions(todayTourLogic)

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Badge
                        variant="warning"
                        render={
                            <button
                                type="button"
                                onClick={(event) => {
                                    // A restart mid-tour would return to a tour step's page when it ends.
                                    if (tourActive) {
                                        return
                                    }
                                    // pinned: analytics event name.
                                    posthog.capture('today nav beta badge clicked')
                                    startTour(clickPoint(event))
                                }}
                                aria-label="Take the design tour"
                                data-attr="today-rail-beta-tour"
                            />
                        }
                        className="shrink-0 cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                    >
                        BETA
                    </Badge>
                }
            />
            <TooltipContent side="right">The new design is in beta. Click to take the tour again.</TooltipContent>
        </Tooltip>
    )
}
