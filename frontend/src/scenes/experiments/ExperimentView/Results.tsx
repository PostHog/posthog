import '../Experiment.scss'

import { useValues } from 'kea'

import { experimentLogic } from '../experimentLogic'
import { ResultsQuery, ResultsTag } from './components'
import { SummaryTable } from './SummaryTable'

export function Results(): JSX.Element {
    const { experimentResults } = useValues(experimentLogic)

    return (
        <div>
            <div className="inline-flex items-center space-x-2 mb-2">
                <h2 className="m-0 font-semibold text-lg">Results</h2>
                <ResultsTag />
            </div>
            <SummaryTable />
            <ResultsQuery targetResults={experimentResults} showTable={true} />
        </div>
    )
}
