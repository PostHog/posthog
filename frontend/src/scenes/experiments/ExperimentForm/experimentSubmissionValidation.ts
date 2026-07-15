import type { Experiment } from '~/types'

import { getExperimentVariants } from '../utils'
import type { FeatureFlagKeyValidation } from './variantsPanelLogic'
import { getVariantValidationErrors } from './variantsPanelValidation'

export type ExperimentSubmissionValidationResult = {
    isValid: boolean
    errors: string[]
}

export const validateExperimentSubmission = ({
    experiment,
    featureFlagKeyValidation,
    mode,
    experimentErrors,
}: {
    experiment: Experiment
    featureFlagKeyValidation: FeatureFlagKeyValidation | null
    mode: 'create' | 'link'
    experimentErrors: Record<string, string>
}): ExperimentSubmissionValidationResult => {
    const errors: string[] = []

    // Check experiment name
    if (!experiment.name || experiment.name.trim().length === 0) {
        errors.push('Experiment name is required')
    }

    // Check variants
    const variants = getExperimentVariants(experiment)
    const variantErrors = getVariantValidationErrors({
        flagKey: experiment.feature_flag_key,
        variants,
        featureFlagKeyValidation,
        mode,
    })
    errors.push(...variantErrors)

    // The toolbar editor hard-requires 'control', so the backend rejects web experiments without it
    if (experiment.type === 'web' && variants.length > 0 && !variants.some(({ key }) => key === 'control')) {
        errors.push("Web experiments require a variant with key 'control'")
    }

    // Include any other experiment errors
    Object.values(experimentErrors).forEach((error) => {
        if (error && !errors.includes(error)) {
            errors.push(error)
        }
    })

    return {
        isValid: errors.length === 0,
        errors,
    }
}
