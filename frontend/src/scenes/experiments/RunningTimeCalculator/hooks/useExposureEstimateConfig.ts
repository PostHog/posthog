import { useState } from 'react'

import type { Experiment } from '~/types'

import type { ExposureEstimateConfig } from '../runningTimeCalculatorLogic'

export const useExposureEstimateConfig = (
    initialConfig: ExposureEstimateConfig,
    experiment: Experiment,
    loadExposureEstimate: (experiment: Experiment, exposureEstimateConfig: ExposureEstimateConfig) => void
): {
    config: ExposureEstimateConfig
    isDirty: boolean
    updateConfig: (update: ExposureEstimateConfig) => void
    setConfig: React.Dispatch<React.SetStateAction<ExposureEstimateConfig>>
    setIsDirty: () => void
} => {
    /**
     * Exposure Estimate Config Local State.
     * This is the config that the user has selected.
     * It's initializeed with the saved config.
     */
    const [config, setConfig] = useState<ExposureEstimateConfig>(initialConfig)
    /**
     * We need to track if the user has changed any of these values:
     * - exposure estimate config
     * - selected metric
     * - manual conversion rate
     * - minimum detectable effect
     */
    const [isDirty, setIsDirty] = useState(false)

    /**
     * Updates the Exposure Estimate Config, and marks the form as dirty.
     * It also calls the action to load the exposure estimate.
     */
    const updateConfig = (updates: Partial<ExposureEstimateConfig>): void => {
        // Merge the updates with the current config
        const newConfig = { ...config, ...updates } satisfies ExposureEstimateConfig
        // Update the config
        setConfig(newConfig)
        // Mark the form as dirty
        setIsDirty(true)
        // Load the exposure estimate
        loadExposureEstimate(experiment, newConfig)
    }

    return {
        config,
        isDirty,
        updateConfig,
        setConfig,
        setIsDirty: () => setIsDirty(true), // Once dirty, it can't go back.
    }
}
