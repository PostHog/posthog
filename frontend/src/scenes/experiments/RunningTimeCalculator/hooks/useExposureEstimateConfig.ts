import { useState } from 'react'

import type { Experiment } from '~/types'

import type { ExposureEstimateConfig } from '../runningTimeCalculatorLogic'

export const useExposureEstimateConfig = (
    initialConfig: ExposureEstimateConfig,
    experiment: Experiment,
    loadExperimentBaseline: (experiment: Experiment, exposureEstimateConfig: ExposureEstimateConfig) => void
): {
    config: ExposureEstimateConfig
    isDirty: boolean
    patchExposureConfig: (update: Partial<ExposureEstimateConfig>) => void
    setExposureConfig: React.Dispatch<React.SetStateAction<ExposureEstimateConfig>>
    setIsDirty: () => void
} => {
    /**
     * Exposure Estimate Config Local State.
     * This is the config that the user has selected.
     * It's initializeed with the saved config.
     */
    const [estimateConfig, setExposureConfig] = useState<ExposureEstimateConfig>(initialConfig)
    /**
     * We need to track if the user has changed any of these values:
     * - exposure estimate config
     * - selected metric
     * - manual conversion rate
     * - minimum detectable effect
     */
    const [isDirty, setIsDirty] = useState(false)

    /**
     * Updates the Exposure Estimate Config.
     * Side effects:
     * - Marks the form as dirty.
     * - Triggers loadExperimentBaseline with a new config.
     *
     * This is not great, but we had to put our side effects somewhere...
     */
    const patchExposureConfig = (updates: Partial<ExposureEstimateConfig>): void => {
        // Merge the updates with the current config
        const newConfig = { ...estimateConfig, ...updates } satisfies ExposureEstimateConfig
        // Update the config
        setExposureConfig(newConfig)
        // Mark the form as dirty
        setIsDirty(true)
        // Load the exposure estimate
        loadExperimentBaseline(experiment, newConfig)
    }

    return {
        config: estimateConfig,
        isDirty,
        patchExposureConfig,
        setExposureConfig,
        setIsDirty: () => setIsDirty(true), // Once dirty, it can't go back.
    }
}
