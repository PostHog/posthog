import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonLabel } from '@posthog/lemon-ui'

import { GoalLinesList } from 'lib/components/GoalLinesList'
import { goalLinesLogic } from 'scenes/insights/EditorFilters/goalLinesLogic'
import { ShowAlertAnomalyPointsFilter } from 'scenes/insights/EditorFilters/ShowAlertAnomalyPointsFilter'
import { ShowAlertThresholdLinesFilter } from 'scenes/insights/EditorFilters/ShowAlertThresholdLinesFilter'
import { ShowAnnotationsFilter } from 'scenes/insights/EditorFilters/ShowAnnotationsFilter'
import { ShowTrendLinesFilter } from 'scenes/insights/EditorFilters/ShowTrendLinesFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ConfidenceLevelInput } from 'scenes/insights/views/LineGraph/ConfidenceLevelInput'
import { MovingAverageIntervalsInput } from 'scenes/insights/views/LineGraph/MovingAverageIntervalsInput'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { InsightLogicProps } from '~/types'

import { ConfidenceInterval, MovingAverage } from './DisplayOptions'

// Goal lines with the label and the add button on one row, for the Overlays editor section.
export function GoalLinesOverlay({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element {
    const { goalLines } = useValues(goalLinesLogic(insightProps))
    const { addGoalLine, updateGoalLine, removeGoalLine } = useActions(goalLinesLogic(insightProps))

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
                <LemonLabel info="Goal lines can be used to highlight specific goals (Revenue, Signups, etc.) or limits (Web Vitals, etc.)">
                    Goal lines
                </LemonLabel>
                <LemonButton type="secondary" onClick={addGoalLine} icon={<IconPlusSmall />} size="small">
                    Add goal line
                </LemonButton>
            </div>
            {goalLines.length > 0 && (
                <GoalLinesList goalLines={goalLines} removeGoalLine={removeGoalLine} updateGoalLine={updateGoalLine} />
            )}
        </div>
    )
}

// Panel-flavored (switch) variants of the overlay toggles, for the Overlays editor section.
// The same components render as checkboxes in the Options menu when the section flag is off.
export function ShowTrendLinesSwitch(): JSX.Element {
    return <ShowTrendLinesFilter variant="switch" />
}

// One editor filter entry for both alert toggles: the anomaly points toggle only renders when the
// insight has detector alerts, and a null component in its own entry would still take up a slot
// in the panel's flex gap, leaving a phantom double gap.
export function AlertOverlaysSwitches(): JSX.Element | null {
    return (
        <div className="flex flex-col gap-2">
            <ShowAlertThresholdLinesFilter variant="switch" />
            <ShowAlertAnomalyPointsFilter variant="switch" />
        </div>
    )
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
        <div className="flex flex-col gap-2">
            <ConfidenceInterval className="" />
            {showConfidenceIntervals && <ConfidenceLevelInput />}
        </div>
    )
}

export function MovingAverageFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showMovingAverage } = useValues(trendsDataLogic(insightProps))

    return (
        <div className="flex flex-col gap-2">
            <MovingAverage className="" />
            {showMovingAverage && <MovingAverageIntervalsInput />}
        </div>
    )
}
