import { useValues } from 'kea'

import { LemonDivider } from '@posthog/lemon-ui'

import { ShowAlertAnomalyPointsFilter } from 'scenes/insights/EditorFilters/ShowAlertAnomalyPointsFilter'
import { ShowAlertThresholdLinesFilter } from 'scenes/insights/EditorFilters/ShowAlertThresholdLinesFilter'
import { ShowAnnotationsFilter } from 'scenes/insights/EditorFilters/ShowAnnotationsFilter'
import { ShowTrendLinesFilter } from 'scenes/insights/EditorFilters/ShowTrendLinesFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ConfidenceLevelInput } from 'scenes/insights/views/LineGraph/ConfidenceLevelInput'
import { MovingAverageIntervalsInput } from 'scenes/insights/views/LineGraph/MovingAverageIntervalsInput'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { ConfidenceInterval, MovingAverage } from './DisplayOptions'

// Panel-flavored (switch) variants of the overlay toggles, for the Overlays editor section.
// The same components render as checkboxes in the Options menu when the section flag is off.
export function ShowTrendLinesSwitch(): JSX.Element {
    return <ShowTrendLinesFilter variant="switch" />
}

export function ShowAlertThresholdLinesSwitch(): JSX.Element | null {
    return <ShowAlertThresholdLinesFilter variant="switch" />
}

export function ShowAlertAnomalyPointsSwitch(): JSX.Element | null {
    return <ShowAlertAnomalyPointsFilter variant="switch" />
}

export function ShowAnnotationsSwitch(): JSX.Element | null {
    return <ShowAnnotationsFilter variant="switch" />
}

export function OverlaysDivider(): JSX.Element {
    return <LemonDivider className="my-0" />
}

export function ConfidenceIntervalFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showConfidenceIntervals } = useValues(trendsDataLogic(insightProps))

    return (
        <div className="flex flex-col">
            <ConfidenceInterval />
            {showConfidenceIntervals && <ConfidenceLevelInput />}
        </div>
    )
}

export function MovingAverageFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showMovingAverage } = useValues(trendsDataLogic(insightProps))

    return (
        <div className="flex flex-col">
            <MovingAverage />
            {showMovingAverage && <MovingAverageIntervalsInput />}
        </div>
    )
}
