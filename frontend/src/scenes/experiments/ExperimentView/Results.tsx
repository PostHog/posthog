import '../Experiment.scss'

import { useValues } from 'kea'

import { experimentLogic } from '../experimentLogic'
import { ResultsHeader, ResultsQuery } from './components'
import { SummaryTable } from './SummaryTable'
import { DeltaViz } from './DeltaViz'

export function Results(): JSX.Element {
    const { experimentResults } = useValues(experimentLogic)

    return (
        <div>
            <ResultsHeader />
            <SummaryTable />
            <DeltaViz />
            <ResultsQuery targetResults={experimentResults} showTable={true} />
        </div>
    )
}
