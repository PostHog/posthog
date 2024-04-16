import '../Experiment.scss'

import { useValues } from 'kea'

import { experimentLogic } from '../experimentLogic'
import { ResultsHeader, ResultsQuery } from './components'
import { SummaryTable } from './SummaryTable'

export function Results(): JSX.Element {
    const { experimentResults } = useValues(experimentLogic)

    return (
        <div>
            <ResultsHeader />
            <SummaryTable />
            <ResultsQuery targetResults={experimentResults} showTable={true} />
        </div>
    )
}
