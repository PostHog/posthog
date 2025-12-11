import { useActions, useValues } from 'kea'
import { match } from 'ts-pattern'

import { LemonDivider } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { SelectableCard } from '~/scenes/experiments/components/SelectableCard'
import type { Experiment, FeatureFlagType, MultivariateFlagVariant } from '~/types'

import { SelectExistingFeatureFlagModal } from './SelectExistingFeatureFlagModal'
import { VariantsPanelCreateFeatureFlag } from './VariantsPanelCreateFeatureFlag'
import { VariantsPanelLinkFeatureFlag } from './VariantsPanelLinkFeatureFlag'
import { selectExistingFeatureFlagModalLogic } from './selectExistingFeatureFlagModalLogic'
import { variantsPanelLogic } from './variantsPanelLogic'

interface VariantsPanelProps {
    experiment: Experiment
    onPrevious: () => void
    onNext: () => void
    updateFeatureFlag: (featureFlag: {
        feature_flag_key?: string
        parameters?: {
            feature_flag_variants?: MultivariateFlagVariant[]
            ensure_experience_continuity?: boolean
        }
    }) => void
    disabled?: boolean
}

export function VariantsPanel({
    experiment,
    updateFeatureFlag,
    onPrevious,
    onNext,
    disabled = false,
}: VariantsPanelProps): JSX.Element {
    const { mode, linkedFeatureFlag } = useValues(variantsPanelLogic({ experiment, disabled }))
    const { setMode, setLinkedFeatureFlag } = useActions(variantsPanelLogic({ experiment, disabled }))

    const { openSelectExistingFeatureFlagModal, closeSelectExistingFeatureFlagModal } = useActions(
        selectExistingFeatureFlagModalLogic
    )
    const { reportExperimentFeatureFlagSelected } = useActions(eventUsageLogic)

    return (
        <>
            <div className="flex gap-4 mb-4">
                <SelectableCard
                    title="Create new feature flag"
                    description="Generate a new feature flag with custom variants for this experiment."
                    selected={mode === 'create'}
                    onClick={() => {
                        setMode('create')
                    }}
                    disabled={disabled}
                    disabledReason="You cannot change the mode when editing an experiment."
                />
                <SelectableCard
                    title="Link existing feature flag"
                    description="Use an existing multivariate feature flag and inherit its variants."
                    selected={mode === 'link'}
                    onClick={() => setMode('link')}
                    disabled={disabled}
                    disabledReason="You cannot change the mode when editing an experiment."
                />
            </div>

            {match(mode)
                .with('create', () => (
                    <VariantsPanelCreateFeatureFlag
                        experiment={experiment}
                        onChange={updateFeatureFlag}
                        disabled={disabled}
                    />
                ))
                .with('link', () => (
                    <VariantsPanelLinkFeatureFlag
                        linkedFeatureFlag={linkedFeatureFlag}
                        setShowFeatureFlagSelector={openSelectExistingFeatureFlagModal}
                        disabled={disabled}
                    />
                ))
                .exhaustive()}

            <LemonDivider className="mt-4" />
            <div className="flex justify-end pt-4 gap-2">
                <LemonButton type="secondary" size="small" onClick={onPrevious}>
                    Previous
                </LemonButton>
                <LemonButton type="primary" size="small" onClick={onNext}>
                    Next
                </LemonButton>
            </div>

            {/* Feature Flag Selection Modal */}
            <SelectExistingFeatureFlagModal
                onClose={() => closeSelectExistingFeatureFlagModal()}
                onSelect={(flag: FeatureFlagType) => {
                    reportExperimentFeatureFlagSelected(flag.key)
                    setLinkedFeatureFlag(flag)
                    // Update experiment with linked flag's key and variants
                    updateFeatureFlag({
                        feature_flag_key: flag.key,
                        parameters: {
                            feature_flag_variants: flag.filters?.multivariate?.variants || [],
                        },
                    })
                    closeSelectExistingFeatureFlagModal()
                }}
            />
        </>
    )
}
