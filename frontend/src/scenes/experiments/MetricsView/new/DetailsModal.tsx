import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { ExperimentFunnelsQuery, ExperimentMetric, ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import { ResultsBreakdown, ResultsQuery } from '~/scenes/experiments/components/ResultsBreakdown'
import type { Experiment } from '~/types'

interface DetailsModalProps {
    isOpen: boolean
    onClose: () => void
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
    result: any
    experiment: Experiment
}

export function DetailsModal({ isOpen, onClose, metric, result, experiment }: DetailsModalProps): JSX.Element {
    // :KLUDGE: workaround until we pass metric into the Frequentist result response
    result.metric = metric

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={1200}
            title={`Metric results: ${metric.name || 'Untitled metric'}`}
            footer={
                <LemonButton type="secondary" onClick={onClose}>
                    Close
                </LemonButton>
            }
        >
            <ResultsBreakdown result={result} experiment={experiment}>
                {({ query, breakdownResults }) => {
                    return (
                        <>
                            {query && breakdownResults && (
                                <ResultsQuery query={query} breakdownResults={breakdownResults} />
                            )}
                        </>
                    )
                }}
            </ResultsBreakdown>
        </LemonModal>
    )
}
