import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'
import { match } from 'ts-pattern'
import { useDebouncedCallback } from 'use-debounce'

import { LemonDivider } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
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
    showNewExperimentFormLayout?: boolean
}

export function VariantsPanel({
    experiment,
    updateFeatureFlag,
    onPrevious,
    onNext,
    disabled = false,
    showNewExperimentFormLayout = false,
}: VariantsPanelProps): JSX.Element {
    const { mode, linkedFeatureFlag, featureFlagKeyForAutocomplete, featureFlagKeyValidation } = useValues(
        variantsPanelLogic({ experiment, disabled })
    )
    const {
        setMode,
        setLinkedFeatureFlag,
        setFeatureFlagKeyForAutocomplete,
        validateFeatureFlagKey,
        clearFeatureFlagKeyValidation,
    } = useActions(variantsPanelLogic({ experiment, disabled }))

    const { openSelectExistingFeatureFlagModal, closeSelectExistingFeatureFlagModal } = useActions(
        selectExistingFeatureFlagModalLogic
    )
    const { reportExperimentFeatureFlagSelected } = useActions(eventUsageLogic)
    const { featureFlags, featureFlagsLoading } = useValues(selectExistingFeatureFlagModalLogic)
    const { loadFeatureFlagsForAutocomplete } = useActions(selectExistingFeatureFlagModalLogic)

    const debouncedValidateFeatureFlagKey = useDebouncedCallback((key: string) => {
        if (key) {
            validateFeatureFlagKey(key)
        }
    }, 100)

    // Load feature flags on mount for the autocomplete
    useEffect(() => {
        if (showNewExperimentFormLayout) {
            loadFeatureFlagsForAutocomplete()
        }
    }, [showNewExperimentFormLayout, loadFeatureFlagsForAutocomplete])

    const featureFlagOptions = useMemo(() => {
        return (featureFlags.results || []).map((flag) => ({
            key: flag.key,
            label: flag.key,
            value: flag,
        }))
    }, [featureFlags.results])

    // Find the current value for the autocomplete, either an existing flag or a new entry.
    // Returns:
    // An array to comply with LemonInputSelect, even though we're in single-select mode.
    // In case of an existing flag, the full FeatureFlagType object is returned, otherwise a string (feature flag key).
    const currentAutocompleteValue = useMemo(() => {
        if (!featureFlagKeyForAutocomplete) {
            return []
        }
        const matchingFlag = featureFlags.results?.find((flag) => flag.key === featureFlagKeyForAutocomplete)
        if (matchingFlag) {
            return [matchingFlag]
        }
        return [featureFlagKeyForAutocomplete]
    }, [featureFlagKeyForAutocomplete, featureFlags.results])

    const handleFeatureFlagSelection = (selectedKeys: (FeatureFlagType | string)[]): void => {
        if (selectedKeys.length === 0) {
            // Clear validation first to prevent it from being re-triggered by setMode listener
            clearFeatureFlagKeyValidation()
            setLinkedFeatureFlag(null)
            setFeatureFlagKeyForAutocomplete(null)
            updateFeatureFlag({
                feature_flag_key: undefined,
                parameters: {
                    feature_flag_variants: undefined,
                },
            })
            setMode('create')
            return
        }

        const selected = selectedKeys[0]

        if (typeof selected === 'string') {
            // User typed a custom value - create mode
            setLinkedFeatureFlag(null)
            setFeatureFlagKeyForAutocomplete(selected)
            updateFeatureFlag({
                feature_flag_key: selected,
                parameters: {
                    feature_flag_variants: experiment.parameters?.feature_flag_variants || [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                },
            })
            // Change mode after updating the key to avoid validating the old key in setMode listener
            setMode('create')
            debouncedValidateFeatureFlagKey(selected)
        } else {
            // User selected an existing flag - link mode
            setMode('link')
            setLinkedFeatureFlag(selected)
            setFeatureFlagKeyForAutocomplete(selected.key)
            updateFeatureFlag({
                feature_flag_key: selected.key,
                parameters: {
                    feature_flag_variants: selected.filters?.multivariate?.variants || [],
                },
            })
            reportExperimentFeatureFlagSelected(selected.key)
        }
    }

    if (showNewExperimentFormLayout) {
        return (
            <>
                <LemonField.Pure label="Feature flag key" className="mb-4">
                    <>
                        <div className="text-sm text-secondary mb-2">
                            Each experiment is backed by a feature flag. The feature flag key will be used to control
                            the experiment in your code.
                            <br />
                            Type to create a new feature flag or select an existing one. Note that only multivariate
                            feature flags are listed.
                        </div>
                        <LemonInputSelect<FeatureFlagType | string>
                            mode="single"
                            placeholder="Type to create a new feature flag or select an existing one"
                            options={featureFlagOptions}
                            value={currentAutocompleteValue}
                            onChange={handleFeatureFlagSelection}
                            inputTransform={(value) => value.replace(/\s+/g, '-')}
                            allowCustomValues
                            formatCreateLabel={(input) => (
                                <span>
                                    {input}
                                    <span className="text-muted italic"> (new feature flag)</span>
                                </span>
                            )}
                            loading={featureFlagsLoading}
                            disabled={disabled}
                            fullWidth
                        />
                        {featureFlagKeyValidation?.error && (
                            <div className="text-xs text-danger mt-1">{featureFlagKeyValidation.error}</div>
                        )}
                    </>
                </LemonField.Pure>

                {featureFlagKeyForAutocomplete &&
                    match(mode)
                        .with('create', () => (
                            <VariantsPanelCreateFeatureFlag
                                experiment={experiment}
                                onChange={updateFeatureFlag}
                                disabled={disabled}
                                showNewExperimentFormLayout={showNewExperimentFormLayout}
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

                {/* Feature Flag Selection Modal */}
                <SelectExistingFeatureFlagModal
                    onClose={() => closeSelectExistingFeatureFlagModal()}
                    onSelect={(flag: FeatureFlagType) => {
                        reportExperimentFeatureFlagSelected(flag.key)
                        setLinkedFeatureFlag(flag)
                        // VariantsPanelLinkFeatureFlag shows a "change" button which we want to keep in sync with the autocomplete
                        setFeatureFlagKeyForAutocomplete(flag.key)
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
                        showNewExperimentFormLayout={showNewExperimentFormLayout}
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
