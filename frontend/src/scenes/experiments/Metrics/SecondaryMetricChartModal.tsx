import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { useValues } from 'kea'

import { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { ResultsQuery } from '../ExperimentView/components'

export function SecondaryMetricChartModal({
    experimentId,
    metricIdx,
    isOpen,
    onClose,
}: {
    experimentId: Experiment['id']
    metricIdx: number
    isOpen: boolean
    onClose: () => void
}): JSX.Element {
    const { secondaryMetricResults } = useValues(experimentLogic({ experimentId }))
    const targetResults = secondaryMetricResults && secondaryMetricResults[metricIdx]

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={1000}
            title="Results"
            footer={
                <LemonButton form="secondary-metric-modal-form" type="secondary" onClick={onClose}>
                    Close
                </LemonButton>
            }
        >
            <ResultsQuery result={targetResults} showTable={false} />
        </LemonModal>
    )
}
