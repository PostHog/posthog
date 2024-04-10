import '../Experiment.scss'

import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { experimentLogic } from '../experimentLogic'
import { ResultsQuery, ResultsTag } from './components'
import { SummaryTable } from './SummaryTable'

export function Results(): JSX.Element {
    const { experimentResults } = useValues(experimentLogic)

    return (
        <div>
            <div className="flex">
                <div className="w-1/2">
                    <div className="inline-flex items-center space-x-2 mb-2">
                        <h2 className="m-0 font-semibold text-lg">Results</h2>
                        <ResultsTag />
                    </div>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto">
                        <LemonButton
                            className="ml-auto -translate-y-2"
                            size="small"
                            type="secondary"
                            icon={<IconAreaChart />}
                            to={urls.insightNew(
                                undefined,
                                undefined,
                                JSON.stringify({
                                    kind: NodeKind.InsightVizNode,
                                    source: filtersToQueryNode(
                                        transformResultFilters(
                                            experimentResults?.filters
                                                ? { ...experimentResults.filters, explicit_date: true }
                                                : {}
                                        )
                                    ),
                                    showTable: true,
                                    showLastComputation: true,
                                    showLastComputationRefresh: false,
                                })
                            )}
                        >
                            Explore
                        </LemonButton>
                    </div>
                </div>
            </div>
            <SummaryTable />
            <ResultsQuery targetResults={experimentResults} showTable={true} />
        </div>
    )
}
