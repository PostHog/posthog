/**
 * Example usage of SampledSessionsModal with experiment funnel data
 *
 * This component demonstrates how to integrate the SampledSessionsModal
 * with experiment results that include steps_event_data.
 */

import { useState } from 'react'
import { LemonButton } from '@posthog/lemon-ui'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { SampledSessionsModal } from './SampledSessionsModal'
import {
    ExperimentFunnelMetric,
    CachedNewExperimentQueryResponse,
    NodeKind
} from '~/queries/schema/schema-general'

interface ExampleProps {
    experimentResult: CachedNewExperimentQueryResponse
    metric: ExperimentFunnelMetric
    variantKey: string
}

export function SampledSessionsModalExample({ experimentResult, metric, variantKey }: ExampleProps): JSX.Element {
    const [isModalOpen, setIsModalOpen] = useState(false)

    // Get the variant result based on the variant key
    const getVariantResult = (): any => {
        if (variantKey === 'control') {
            return experimentResult.baseline
        }
        const variantIndex = experimentResult.variant_results?.findIndex(v => v.key === variantKey)
        return variantIndex !== undefined && variantIndex >= 0
            ? experimentResult.variant_results![variantIndex]
            : null
    }

    const variantResult = getVariantResult()

    // Extract step names from the funnel metric
    const getStepNames = (): string[] => {
        if (!metric.series) {
            return []
        }

        return metric.series.map((step, index) => {
            if (step.kind === NodeKind.EventsNode) {
                return step.name || step.event || `Step ${index + 1}`
            } else if (step.kind === NodeKind.ActionsNode) {
                return step.name || `Action ${step.id}`
            }
            return `Step ${index + 1}`
        })
    }

    if (!variantResult || !variantResult.steps_event_data) {
        return (
            <div className="text-muted">
                No session data available for this variant
            </div>
        )
    }

    return (
        <>
            <LemonButton
                type="secondary"
                icon={<IconPlayCircle />}
                onClick={() => setIsModalOpen(true)}
            >
                View Sampled Sessions
            </LemonButton>

            <SampledSessionsModal
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                stepsEventData={variantResult.steps_event_data}
                stepNames={getStepNames()}
                variant={variantKey}
            />
        </>
    )
}

/**
 * Example of how to use this in a parent component:
 *
 * ```tsx
 * // In your experiment results component:
 * import { SampledSessionsModalExample } from './SampledSessionsModalExample'
 *
 * function ExperimentResults() {
 *     const { experimentResult, experiment } = useValues(experimentLogic)
 *
 *     if (isExperimentFunnelMetric(experiment.metric)) {
 *         return (
 *             <div>
 *                 {experiment.parameters?.feature_flag_variants?.map(variant => (
 *                     <div key={variant.key}>
 *                         <h3>{variant.key}</h3>
 *                         <SampledSessionsModalExample
 *                             experimentResult={experimentResult}
 *                             metric={experiment.metric}
 *                             variantKey={variant.key}
 *                         />
 *                     </div>
 *                 ))}
 *             </div>
 *         )
 *     }
 * }
 * ```
 */