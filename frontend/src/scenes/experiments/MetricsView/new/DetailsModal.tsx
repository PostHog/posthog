import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { ExperimentFunnelsQuery, ExperimentMetric, ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { ResultDetails } from './ResultDetails'

interface DetailsModalProps {
    isOpen: boolean
    onClose: () => void
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
    metricIndex: number
    isSecondary: boolean
    result: any
    experiment: Experiment
}

export function DetailsModal({
    isOpen,
    onClose,
    metric,
    result,
    experiment,
    metricIndex,
    isSecondary,
}: DetailsModalProps): JSX.Element {
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
            <ResultDetails
                result={result}
                experiment={experiment}
                metric={metric as ExperimentMetric}
                metricIndex={metricIndex}
                isSecondary={isSecondary}
            />
        </LemonModal>
    )
}
