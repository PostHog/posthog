import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { slugifyFeatureFlagKey } from 'scenes/feature-flags/featureFlagLogic'

import { Experiment } from '~/types'

import { ExperimentFlagKeyInput } from './ExperimentFlagKeyInput'

interface DuplicateExperimentModalProps {
    isOpen: boolean
    onClose: () => void
    experiment: Experiment
}

export function DuplicateExperimentModal({ isOpen, onClose, experiment }: DuplicateExperimentModalProps): JSX.Element {
    const {
        featureFlagModalFeatureFlags,
        featureFlagModalFeatureFlagsLoading,
        featureFlagModalFilters,
        featureFlagModalPagination,
    } = useValues(experimentsLogic)
    const { duplicateExperiment, setFeatureFlagModalFilters, resetFeatureFlagModalFilters } =
        useActions(experimentsLogic)

    const [experimentName, setExperimentName] = useState('')
    const [flagKey, setFlagKey] = useState('')
    const [flagKeyManuallyEdited, setFlagKeyManuallyEdited] = useState(false)
    const [isExistingFlag, setIsExistingFlag] = useState(false)
    const [showReuseFlag, setShowReuseFlag] = useState(false)

    const handleNameChange = (value: string): void => {
        setExperimentName(value)
        if (!flagKeyManuallyEdited) {
            setFlagKey(slugifyFeatureFlagKey(value, { fromTitleInput: true }))
            setIsExistingFlag(false)
        }
    }

    const handleFlagKeyChange = (value: string): void => {
        setFlagKeyManuallyEdited(true)
        setIsExistingFlag(false)
        setFlagKey(slugifyFeatureFlagKey(value))
    }

    const selectExistingFlag = (key: string): void => {
        setFlagKeyManuallyEdited(true)
        setIsExistingFlag(true)
        setFlagKey(key)
    }

    const handleDuplicate = (): void => {
        duplicateExperiment({
            id: experiment.id as number,
            featureFlagKey: flagKey || undefined,
            name: experimentName.trim() || undefined,
        })
        handleClose()
    }

    const handleClose = (): void => {
        resetFeatureFlagModalFilters()
        setExperimentName('')
        setFlagKey('')
        setFlagKeyManuallyEdited(false)
        setIsExistingFlag(false)
        setShowReuseFlag(false)
        onClose()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={handleClose}
            title="Duplicate experiment"
            width="max-content"
            footer={
                <div className="flex justify-end">
                    <LemonButton type="primary" onClick={handleDuplicate} data-attr="duplicate-experiment-submit">
                        Duplicate
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
                <div className="text-muted max-w-xl">
                    Create a new experiment using the configuration from <strong>{experiment.name}</strong>.
                </div>

                <div>
                    <label className="font-semibold mb-1 block">Experiment name</label>
                    <LemonInput
                        value={experimentName}
                        onChange={handleNameChange}
                        placeholder={`${experiment.name} (Copy)`}
                        autoFocus
                        data-attr="duplicate-experiment-name"
                    />
                </div>

                <ExperimentFlagKeyInput
                    flagKey={flagKey}
                    onFlagKeyChange={handleFlagKeyChange}
                    isExistingFlag={isExistingFlag}
                    sourceExperiment={experiment}
                    featureFlags={featureFlagModalFeatureFlags}
                    featureFlagsLoading={featureFlagModalFeatureFlagsLoading}
                    featureFlagFilters={featureFlagModalFilters}
                    onFeatureFlagFiltersChange={setFeatureFlagModalFilters}
                    featureFlagPagination={featureFlagModalPagination}
                    onSelectExistingFlag={selectExistingFlag}
                    showReuseFlag={showReuseFlag}
                    onToggleReuseFlag={setShowReuseFlag}
                />
            </div>
        </LemonModal>
    )
}
