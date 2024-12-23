import { useValues } from 'kea'

import { experimentLogic } from '../experimentLogic'
import { ResultsHeader, ResultsQuery } from './components'
import { SummaryTable } from './SummaryTable'

export function Results(): JSX.Element {
    const { metricResults } = useValues(experimentLogic)
    const result = metricResults?.[0]
    if (!result) {
        return <></>
    }

    return (
        <div>
            <ResultsHeader />
            <SummaryTable />
            <ResultsQuery targetResults={result} showTable={true} />
        </div>
    )
}
