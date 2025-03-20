import { useActions, useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'

import { experimentLogic } from '../experimentLogic'
import ExperimentDate from './ExperimentDate'

export function ExperimentDates(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { changeExperimentStartDate, changeExperimentEndDate } = useActions(experimentLogic)
    const { created_at, start_date, end_date } = experiment

    // If the experiment has no start date and no creation date, don't show anything
    if (!start_date && !created_at) {
        return <></>
    }

    // If the experiment has no start date but has a creation date, show the creation date.
    // This also narrows the type of created_at to be non-null
    if (!start_date && created_at) {
        return (
            <div className="block" data-attr="experiment-creation-date">
                <div className="text-xs font-semibold uppercase tracking-wide">Creation date</div>
                <TZLabel time={created_at} />
            </div>
        )
    }

    // If the experiment has a start date, show the start date and end date
    return (
        <>
            <ExperimentDate label="Start date" date={start_date} onChange={changeExperimentStartDate} />
            <ExperimentDate label="End date" date={end_date} onChange={changeExperimentEndDate} />
        </>
    )
}
