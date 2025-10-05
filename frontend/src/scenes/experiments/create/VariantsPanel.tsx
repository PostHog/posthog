import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { match } from 'ts-pattern'

import { SelectableCard } from '~/scenes/experiments/components/SelectableCard'
import type { Experiment, FeatureFlagType, MultivariateFlagVariant } from '~/types'

import { SelectExistingFeatureFlagModal } from './SelectExistingFeatureFlagModal'
import { VariantsPanelCreateFeatureFlag } from './VariantsPanelCreateFeatureFlag'
import { VariantsPanelLinkFeatureFlag } from './VariantsPanelLinkFeatureFlag'
import { selectExistingFeatureFlagModalLogic } from './selectExistingFeatureFlagModalLogic'
import { variantsPanelLogic } from './variantsPanelLogic'

interface VariantsPanelProps {
    experiment: Experiment
    updateFeatureFlag: (featureFlag: {
        feature_flag_key?: string
        parameters?: {
            feature_flag_variants?: MultivariateFlagVariant[]
            ensure_experience_continuity?: boolean
        }
    }) => void
}

export function VariantsPanel({ experiment, updateFeatureFlag }: VariantsPanelProps): JSX.Element {
    const { mode } = useValues(variantsPanelLogic)
    const { setMode } = useActions(variantsPanelLogic)

    const [linkedFeatureFlag, setLinkedFeatureFlag] = useState<FeatureFlagType | null>(null)

    const { openSelectExistingFeatureFlagModal, closeSelectExistingFeatureFlagModal } = useActions(
        selectExistingFeatureFlagModalLogic
    )

    return (
        <div className="space-y-6">
            <div className="flex gap-4 mb-6">
                <SelectableCard
                    title="Create new feature flag"
                    description="Generate a new feature flag with custom variants for this experiment."
                    selected={mode === 'create'}
                    onClick={() => {
                        setMode('create')
                    }}
                />
                <SelectableCard
                    title="Link existing feature flag"
                    description="Use an existing multivariate feature flag and inherit its variants."
                    selected={mode === 'link'}
                    onClick={() => setMode('link')}
                />
            </div>

            {match(mode)
                .with('create', () => (
                    <VariantsPanelCreateFeatureFlag experiment={experiment} onChange={updateFeatureFlag} />
                ))
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
