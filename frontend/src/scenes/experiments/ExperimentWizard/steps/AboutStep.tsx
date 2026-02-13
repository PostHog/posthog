import { useActions, useValues } from 'kea'

import { LemonInput, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { slugify } from 'lib/utils'

import { SelectExistingFeatureFlagModal } from '../../ExperimentForm/SelectExistingFeatureFlagModal'
import { VariantsPanelLinkFeatureFlag } from '../../ExperimentForm/VariantsPanelLinkFeatureFlag'
import { selectExistingFeatureFlagModalLogic } from '../../ExperimentForm/selectExistingFeatureFlagModalLogic'
import { experimentWizardLogic } from '../experimentWizardLogic'

export function AboutStep(): JSX.Element {
    const { experiment, linkedFeatureFlag } = useValues(experimentWizardLogic)
    const { setExperimentValue, setFeatureFlagConfig, setLinkedFeatureFlag } = useActions(experimentWizardLogic)
    const { openSelectExistingFeatureFlagModal, closeSelectExistingFeatureFlagModal } = useActions(
        selectExistingFeatureFlagModalLogic
    )

    return (
        <div className="space-y-6">
            <h3 className="text-lg font-semibold">What are we testing?</h3>

            <LemonField.Pure label="Experiment name">
                <LemonInput
                    placeholder="e.g., New checkout flow test"
                    value={experiment.name}
                    onChange={(value) => {
                        setExperimentValue('name', value)
                        if (!experiment.feature_flag_key || experiment.feature_flag_key === slugify(experiment.name)) {
                            setExperimentValue('feature_flag_key', slugify(value))
                        }
                    }}
                    data-attr="experiment-wizard-name"
                />
            </LemonField.Pure>

            <LemonField.Pure label="Hypothesis" info="Describe what you expect to happen and why.">
                <LemonTextArea
                    placeholder="We believe that ... will result in ... because ..."
                    value={experiment.description ?? ''}
                    onChange={(value) => setExperimentValue('description', value)}
                    data-attr="experiment-wizard-hypothesis"
                    minRows={3}
                />
            </LemonField.Pure>

            {linkedFeatureFlag ? (
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={linkedFeatureFlag}
                    setShowFeatureFlagSelector={openSelectExistingFeatureFlagModal}
                    onRemove={() => {
                        setLinkedFeatureFlag(null)
                        setExperimentValue('feature_flag_key', '')
                    }}
                />
            ) : (
                <LemonField.Pure label="Feature flag key">
                    <div className="flex items-center gap-2">
                        <LemonInput
                            placeholder="e.g., new-checkout-flow-test"
                            value={experiment.feature_flag_key ?? ''}
                            onChange={(value) => setExperimentValue('feature_flag_key', value)}
                            data-attr="experiment-wizard-flag-key"
                            fullWidth
                        />
                    </div>
                    <div className="flex items-center justify-end gap-1 text-sm">
                        Do you have a feature flag already?{' '}
                        <Link className="whitespace-nowrap text-sm" subtle onClick={openSelectExistingFeatureFlagModal}>
                            Select existing flag
                        </Link>
                    </div>
                </LemonField.Pure>
            )}

            <SelectExistingFeatureFlagModal
                onClose={closeSelectExistingFeatureFlagModal}
                onSelect={(flag) => {
                    setLinkedFeatureFlag(flag)
                    setFeatureFlagConfig({
                        feature_flag_key: flag.key,
                        feature_flag_variants: flag.filters?.multivariate?.variants || [],
                    })
                    closeSelectExistingFeatureFlagModal()
                }}
            />
        </div>
    )
}
