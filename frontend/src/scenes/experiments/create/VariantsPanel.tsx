import { useActions } from 'kea'
import { useState } from 'react'
import { match } from 'ts-pattern'

import { SelectableCard } from '~/scenes/experiments/components/SelectableCard'
import type { Experiment, FeatureFlagType, MultivariateFlagVariant } from '~/types'

import { SelectExistingFeatureFlagModal } from './SelectExistingFeatureFlagModal'
import { VariantsPanelCreateFeatureFlag } from './VariantsPanelCreateFeatureFlag'
import { VariantsPanelLinkFeatureFlag } from './VariantsPanelLinkFeatureFlag'
import { selectExistingFeatureFlagModalLogic } from './selectExistingFeatureFlagModalLogic'

interface VariantsPanelProps {
    experiment: Experiment
    onChange: (updates: {
        feature_flag_key?: string
        parameters?: {
            feature_flag_variants?: MultivariateFlagVariant[]
            ensure_experience_continuity?: boolean
        }
    }) => void
}

export function VariantsPanel({ experiment, onChange }: VariantsPanelProps): JSX.Element {
    // we'll use local state to handle selectors and modals
    const [flagSourceMode, setFlagSourceMode] = useState<'create' | 'link'>('create')
    const [linkedFeatureFlag, setLinkedFeatureFlag] = useState<FeatureFlagType | null>(null)

    const { openSelectExistingFeatureFlagModal, closeSelectExistingFeatureFlagModal } = useActions(
        selectExistingFeatureFlagModalLogic
    )

    return (
        <div className="space-y-6">
            {/* Feature Flag Source Selection */}
            <div>
                <h3 className="font-semibold mb-3">Feature Flag Configuration</h3>
                <div className="flex gap-4 mb-6">
                    <SelectableCard
                        title="Create new feature flag"
                        description="Generate a new feature flag with custom variants for this experiment."
                        selected={flagSourceMode === 'create'}
                        onClick={() => {
                            setFlagSourceMode('create')
                        }}
                    />
                    <SelectableCard
                        title="Link existing feature flag"
                        description="Use an existing multivariate feature flag and inherit its variants."
                        selected={flagSourceMode === 'link'}
                        onClick={() => setFlagSourceMode('link')}
                    />
                </div>
            </div>

            {match(flagSourceMode)
                .with('create', () => <VariantsPanelCreateFeatureFlag experiment={experiment} onChange={onChange} />)
                .with('link', () => (
                    <VariantsPanelLinkFeatureFlag
                        linkedFeatureFlag={linkedFeatureFlag}
                        setShowFeatureFlagSelector={openSelectExistingFeatureFlagModal}
                    />
                ))
                .exhaustive()}

            {/* Feature Flag Selection Modal */}
            <SelectExistingFeatureFlagModal
                onClose={() => closeSelectExistingFeatureFlagModal()}
                onSelect={(flag: FeatureFlagType) => {
                    setLinkedFeatureFlag(flag)
                    closeSelectExistingFeatureFlagModal()
                }}
            />
        </div>
    )
}
