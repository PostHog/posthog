import '../Experiment.scss'

import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'

import { experimentLogic } from '../experimentLogic'
import { ResultsHeader, ResultsQuery } from './components'
import { DeltaViz } from './DeltaViz'
import { SummaryTable } from './SummaryTable'

export function Results(): JSX.Element {
    const { experimentResults, featureFlags } = useValues(experimentLogic)

    return (
        <div>
            <ResultsHeader />
            <SummaryTable />
            {featureFlags[FEATURE_FLAGS.EXPERIMENTS_MULTIPLE_METRICS] && <DeltaViz />}
            <ResultsQuery targetResults={experimentResults} showTable={true} />
        </div>
    )
}
