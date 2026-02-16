import { useActions, useValues } from 'kea'
import { useDebouncedCallback } from 'use-debounce'

import { LemonInput, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { slugify } from 'lib/utils'

import { SelectExistingFeatureFlagModal } from '../../ExperimentForm/SelectExistingFeatureFlagModal'
import { VariantsPanelLinkFeatureFlag } from '../../ExperimentForm/VariantsPanelLinkFeatureFlag'
import { selectExistingFeatureFlagModalLogic } from '../../ExperimentForm/selectExistingFeatureFlagModalLogic'
import { experimentWizardLogic } from '../experimentWizardLogic'

export function AboutStep(): JSX.Element {
    const { experiment, linkedFeatureFlag, featureFlagKeyValidation, featureFlagKeyValidationLoading, departedSteps } =
        useValues(experimentWizardLogic)
    const {
        setExperimentValue,
        setFeatureFlagConfig,
        setLinkedFeatureFlag,
        validateFeatureFlagKey,
        clearFeatureFlagKeyValidation,
    } = useActions(experimentWizardLogic)
    const { openSelectExistingFeatureFlagModal, closeSelectExistingFeatureFlagModal } = useActions(
        selectExistingFeatureFlagModalLogic
    )

    const debouncedValidateFeatureFlagKey = useDebouncedCallback((key: string) => {
        if (key) {
            validateFeatureFlagKey(key)
        } else {
            clearFeatureFlagKeyValidation()
        }
    }, 300)

    const isDeparted = !!departedSteps.about
    const nameError = isDeparted && !experiment.name?.trim() ? 'Name is required' : undefined
    const featureFlagKeyError =
        (!linkedFeatureFlag && featureFlagKeyValidation?.valid === false
            ? featureFlagKeyValidation.error
            : undefined) ??
        (isDeparted && !experiment.feature_flag_key?.trim() ? 'Feature flag key is required' : undefined)

    return (
        <div className="space-y-6">
            <h3 className="text-lg font-semibold">What are we testing?</h3>

            <LemonField.Pure label="Experiment name" error={nameError}>
                <LemonInput
                    placeholder="e.g., New checkout flow test"
                    value={experiment.name}
                    onChange={(value) => {
                        setExperimentValue('name', value)
                        if (!experiment.feature_flag_key || experiment.feature_flag_key === slugify(experiment.name)) {
                            const newKey = slugify(value)
                            setExperimentValue('feature_flag_key', newKey)
                            debouncedValidateFeatureFlagKey(newKey)
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
                        clearFeatureFlagKeyValidation()
                    }}
                />
            ) : (
                <LemonField.Pure
                    label={
                        <div className="flex items-center justify-between w-full">
                            <span>Feature flag key</span>
                            <span className="text-muted text-sm font-normal">
                                Do you have a feature flag already?{' '}
                                <Link
                                    className="whitespace-nowrap text-sm"
                                    subtle
                                    onClick={openSelectExistingFeatureFlagModal}
                                >
                                    Select existing flag
                                </Link>
                            </span>
                        </div>
                    }
                    error={featureFlagKeyError}
                >
                    <LemonInput
                        placeholder="e.g., new-checkout-flow-test"
                        value={experiment.feature_flag_key ?? ''}
                        onChange={(value) => {
                            const normalizedValue = slugify(value, { trimBothEnds: false })
                            setExperimentValue('feature_flag_key', normalizedValue)
                            debouncedValidateFeatureFlagKey(normalizedValue)
                        }}
                        suffix={featureFlagKeyValidationLoading ? <Spinner className="text-xl" /> : undefined}
                        data-attr="experiment-wizard-flag-key"
                        fullWidth
                    />
                </LemonField.Pure>
            )}

            <SelectExistingFeatureFlagModal
                onClose={closeSelectExistingFeatureFlagModal}
                onSelect={(flag) => {
                    setLinkedFeatureFlag(flag)
                    clearFeatureFlagKeyValidation()
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
