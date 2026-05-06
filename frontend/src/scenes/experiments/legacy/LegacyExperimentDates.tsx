import { useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { Label } from 'lib/ui/Label/Label'

import { LegacyExperimentDate, legacyExperimentLogic } from '~/scenes/experiments/legacy'

/**
 * @deprecated use the ExperimentDuration component instead
 */
export function LegacyExperimentDates(): JSX.Element | null {
    const { experiment } = useValues(legacyExperimentLogic)
    const { created_at, start_date, end_date } = experiment

    // If the experiment has no start date and no creation date, don't show anything
    if (!start_date && !created_at) {
        return null
    }

    // If the experiment has no start date but has a creation date, show the creation date.
    // This also narrows the type of created_at to be non-null
    if (!start_date && created_at) {
        return (
            <div className="flex flex-col" data-attr="experiment-creation-date">
                <Label intent="menu">Creation date</Label>
                <TZLabel time={created_at} />
            </div>
        )
    }

    // If the experiment has a start date, show the start date and end date
    return (
        <>
            <LegacyExperimentDate label="Start Date" date={start_date} data-attr="experiment-start-date" />
            <LegacyExperimentDate label="End Date" date={end_date} data-attr="experiment-end-date" />
        </>
    )
}
