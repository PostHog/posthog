import { useActions, useValues } from 'kea'

import { IconFlask } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import type { FeatureFlagType } from '~/types'

import { createDraftExperimentFromFlagLogic } from './createDraftExperimentFromFlagLogic'

export interface CreateDraftExperimentCardProps {
    featureFlag: FeatureFlagType
}

export function CreateDraftExperimentCard({ featureFlag }: CreateDraftExperimentCardProps): JSX.Element {
    const logic = createDraftExperimentFromFlagLogic({
        featureFlagKey: featureFlag.key,
        featureFlagVariants: featureFlag.filters.multivariate?.variants || [],
    })

    const { experimentName, experimentDescription, isLoading, error } = useValues(logic)
    const { setExperimentName, setExperimentDescription, createDraftExperiment } = useActions(logic)

    return (
        <div className="border rounded p-4 bg-bg-light">
            <h3 className="text-lg font-semibold mb-2 flex items-center gap-2">
                <IconFlask className="text-lg" />
                Create experiment for this flag
            </h3>
            <p className="text-sm text-muted mb-4">
                Quickly create a draft experiment using this feature flag. You'll configure metrics in the next step.
            </p>

            <div className="space-y-3">
                <div>
                    <label className="block text-sm font-medium mb-1">
                        Experiment name <span className="text-danger">*</span>
                    </label>
                    <LemonInput
                        value={experimentName}
                        onChange={setExperimentName}
                        placeholder="e.g., Test new checkout flow"
                        disabled={isLoading}
                        autoFocus
                    />
                </div>

                <div>
                    <label className="block text-sm font-medium mb-1">
                        Hypothesis <span className="text-muted-alt">(optional)</span>
                    </label>
                    <LemonTextArea
                        value={experimentDescription}
                        onChange={setExperimentDescription}
                        placeholder="Describe what you're testing and what you expect to happen..."
                        disabled={isLoading}
                        rows={3}
                    />
                </div>

                {error && <div className="text-danger text-sm">{error}</div>}

                <div className="flex gap-2">
                    <LemonButton
                        type="primary"
                        onClick={createDraftExperiment}
                        loading={isLoading}
                        disabledReason={!experimentName.trim() ? 'Name is required' : undefined}
                    >
                        Create draft
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
