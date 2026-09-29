import { useActions, useValues } from 'kea'
import { useDebouncedCallback } from 'use-debounce'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonInput, Link, Tooltip } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { slugifyFeatureFlagKey } from 'scenes/feature-flags/featureFlagLogic'

import type { FeatureFlagType } from '~/types'

import { SelectExistingFeatureFlagModal } from 'products/experiments/frontend/modals/SelectExistingFeatureFlagModal/SelectExistingFeatureFlagModal'
import { selectExistingFeatureFlagModalLogic } from 'products/experiments/frontend/modals/SelectExistingFeatureFlagModal/selectExistingFeatureFlagModalLogic'

import { VariantsPanelLinkFeatureFlag } from '../../ExperimentForm/VariantsPanelLinkFeatureFlag'
import { getFlagVariants } from '../../utils'
import { experimentWizardLogic } from '../experimentWizardLogic'

/** Marks a required field with a small asterisk. Screen readers hear "(required)" instead. */
function RequiredMark(): JSX.Element {
    return (
        <>
            <span className="text-accent ml-0.5" aria-hidden="true">
                *
            </span>
            <span className="sr-only">(required)</span>
        </>
    )
}

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

    const existingFlag = featureFlagKeyValidation?.existingFlag
    const featureFlagKeyError =
        (!linkedFeatureFlag && featureFlagKeyValidation?.valid === false
            ? featureFlagKeyValidation.error
            : undefined) ??
        (isDeparted && !experiment.feature_flag_key?.trim() ? 'Feature flag key is required' : undefined)

    const linkExistingFlag = (flag: FeatureFlagType): void => {
        setLinkedFeatureFlag(flag)
        clearFeatureFlagKeyValidation()
        setFeatureFlagConfig({
            feature_flag_key: flag.key,
            variants: getFlagVariants(flag),
        })
    }

    return (
        <div className="space-y-6">
            <h3 className="text-lg font-semibold">What are we testing?</h3>

            <LemonField.Pure
                label={
                    <span>
                        Experiment name
                        <RequiredMark />
                    </span>
                }
                error={nameError}
            >
                <LemonInput
                    placeholder="e.g. New checkout flow test"
                    value={experiment.name}
                    onChange={(value) => {
                        setExperimentValue('name', value)
                        if (
                            !experiment.feature_flag_key ||
                            experiment.feature_flag_key ===
                                slugifyFeatureFlagKey(experiment.name, { fromTitleInput: true })
                        ) {
                            const newKey = slugifyFeatureFlagKey(value, { fromTitleInput: true })
                            setExperimentValue('feature_flag_key', newKey)
                            debouncedValidateFeatureFlagKey(newKey)
                        }
                    }}
                    data-attr="experiment-wizard-name"
                />
            </LemonField.Pure>

            <LemonField.Pure label="Hypothesis" info="Describe what you expect to happen and why." showOptional>
                <LemonTextArea
                    placeholder="We believe that ... will result in ... because ..."
                    value={experiment.description ?? ''}
                    onChange={(value) => setExperimentValue('description', value)}
                    data-attr="experiment-wizard-hypothesis"
                    minRows={3}
                    maxLength={3000}
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
                            <span className="flex items-center gap-1">
                                <span>
                                    Feature flag key
                                    <RequiredMark />
                                </span>
                                <Tooltip title="The experiment uses this flag to decide which variant each person sees. Your code checks it to show them that variant.">
                                    <IconInfo className="text-xl text-secondary shrink-0" />
                                </Tooltip>
                            </span>
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
                    renderError={
                        existingFlag
                            ? (error) => (
                                  <div className="text-danger flex items-center gap-1 text-sm">
                                      {error}{' '}
                                      <LemonButton
                                          type="secondary"
                                          size="xsmall"
                                          onClick={() => linkExistingFlag(existingFlag)}
                                          data-attr="experiment-wizard-link-existing-flag"
                                      >
                                          Use this flag
                                      </LemonButton>
                                  </div>
                              )
                            : // undefined results in using default error rendering
                              undefined
                    }
                >
                    <LemonInput
                        placeholder="e.g. new-checkout-flow-test"
                        value={experiment.feature_flag_key ?? ''}
                        onChange={(value) => {
                            const normalizedValue = slugifyFeatureFlagKey(value)
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
                    linkExistingFlag(flag)
                    closeSelectExistingFeatureFlagModal()
                }}
            />
        </div>
    )
}
