import './Experiment.scss'

import { LemonTag, LemonTagType } from '@posthog/lemon-ui'
import { useValues } from 'kea'

import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { InsightShortId } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { transformResultFilters } from '../utils'
import { SummaryTable } from './SummaryTable'

export function ResultsTag(): JSX.Element {
    const { areResultsSignificant } = useValues(experimentLogic)
    const result: { color: LemonTagType; label: string } = areResultsSignificant
        ? { color: 'success', label: 'Significant' }
        : { color: 'primary', label: 'Not significant' }

    return (
        <LemonTag type={result.color}>
            <b className="uppercase">{result.label}</b>
        </LemonTag>
    )
}

export function Results(): JSX.Element {
    const { experimentResults } = useValues(experimentLogic)

    return (
        <div>
            <div className="inline-flex items-center space-x-2 mb-2">
                <h2 className="m-0 font-semibold text-lg">Results</h2>
                <ResultsTag />
            </div>
            <SummaryTable />
            <Query
                query={{
                    kind: NodeKind.InsightVizNode,
                    source: filtersToQueryNode(transformResultFilters(experimentResults?.filters ?? {})),
                    showTable: true,
                    showLastComputation: true,
                    showLastComputationRefresh: false,
                }}
                context={{
                    insightProps: {
                        dashboardItemId: experimentResults?.fakeInsightId as InsightShortId,
                        cachedInsight: {
                            short_id: experimentResults?.fakeInsightId as InsightShortId,
                            filters: transformResultFilters(experimentResults?.filters ?? {}),
                            result: experimentResults?.insight,
                            disable_baseline: true,
                            last_refresh: experimentResults?.last_refresh,
                        },
                        doNotLoad: true,
                    },
                }}
                readOnly
            />
        </div>
    )
}
