import { useActions, useValues } from 'kea'

import { DropdownMenuItem } from '@posthog/quill'

import { navSwitchLogic } from 'lib/components/NavSwitch/navSwitchLogic'

import { clickPoint } from './todayTourGeometry'
import { todayTourLogic } from './todayTourLogic'

/**
 * Starts the design tour from the new navigation's "More" menu. It also reaches people enrolled without the switch,
 * who never see the dialog that offers the tour. Hidden where the switch flag is off, so experiment cohorts are left alone.
 */
export function TodayTakeTourMenuItem(): JSX.Element | null {
    const { switchFlagOn } = useValues(navSwitchLogic)
    const { tourActive } = useValues(todayTourLogic)
    const { startTour } = useActions(todayTourLogic)

    if (!switchFlagOn || tourActive) {
        return null
    }

    return (
        <DropdownMenuItem
            // The tour's cursor starts where this click happened.
            onClick={(event) => startTour(clickPoint(event))}
            data-attr="more-menu-take-tour-button"
        >
            Take the tour
        </DropdownMenuItem>
    )
}
