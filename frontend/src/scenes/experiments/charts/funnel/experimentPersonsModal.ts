import { funnelTitle } from 'scenes/trends/persons-modal/persons-modal-utils'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { ExperimentActorsQuery, ExperimentQuery, NodeKind } from '~/queries/schema/schema-general'
import { EXPOSURE_DEFAULT_EVENT } from '~/scenes/experiments/exposureContract'
import { Experiment, StepOrderValue } from '~/types'

/**
 * `funnelStep` for the actors query behind a click on frontend step `stepIndex`, or null when the
 * click isn't queryable. The frontend prepends an "Experiment exposure" step at index 0 that the
 * backend actors funnel doesn't have, so frontend index N maps to backend step number N, negated
 * for drop-offs. The exposure step itself can't be queried, and neither can drop-offs at the first
 * metric step ("exposed but never entered the funnel").
 */
export function experimentActorsFunnelStep(stepIndex: number, converted: boolean): number | null {
    if (stepIndex < 1 || (!converted && stepIndex === 1)) {
        return null
    }
    return converted ? stepIndex : -stepIndex
}

export function openExperimentPersonsModal({
    stepIndex,
    stepName,
    converted,
    variantKey,
    orderType,
    experimentQuery,
    experiment,
}: {
    stepIndex: number
    stepName: string
    converted: boolean
    variantKey: string
    orderType?: StepOrderValue
    experimentQuery: ExperimentQuery
    experiment: Experiment
}): void {
    const funnelStep = experimentActorsFunnelStep(stepIndex, converted)
    if (funnelStep == null) {
        return
    }

    const query: ExperimentActorsQuery = {
        kind: NodeKind.ExperimentActorsQuery,
        source: experimentQuery,
        funnelStep,
        funnelStepBreakdown: variantKey,
        includeRecordings: true,
        exposureConfig: experiment.exposure_criteria?.exposure_config || {
            kind: NodeKind.ExperimentEventExposureConfig,
            event: EXPOSURE_DEFAULT_EVENT,
            properties: [],
        },
        multipleVariantHandling: experiment.exposure_criteria?.multiple_variant_handling || 'exclude',
        featureFlagKey: experiment.feature_flag?.key || '',
    }

    openPersonsModal({
        title: funnelTitle({
            converted,
            step: stepIndex + 1,
            breakdown_value: variantKey,
            label: stepName,
            order_type: orderType,
        }),
        query,
        additionalSelect: { matched_recordings: 'matched_recordings' },
    })
}
