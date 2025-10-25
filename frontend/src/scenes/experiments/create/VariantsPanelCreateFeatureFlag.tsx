import { useActions, useValues } from 'kea'
import { useDebouncedCallback } from 'use-debounce'

import { IconBalance, IconCheck, IconPlus, IconTrash } from '@posthog/icons'

import { MAX_EXPERIMENT_VARIANTS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { alphabet } from 'lib/utils'

import type { Experiment, MultivariateFlagVariant } from '~/types'

import { percentageDistribution } from '../utils'
import { variantsPanelLogic } from './variantsPanelLogic'

export const generateFeatureFlagKey = (name: string, unavailableFeatureFlagKeys?: Set<string>): string => {
    const baseKey = name
        .toLowerCase()
        .replace(/[^A-Za-z0-9-_]+/g, '-')
        .replace(/-+$/, '')
        .replace(/^-+/, '')

    let key = baseKey
    let counter = 1

    while (unavailableFeatureFlagKeys?.has(key)) {
        key = `${baseKey}-${counter}`
        counter++
    }
    return key
}

interface VariantsPanelCreateFeatureFlagProps {
    experiment: Experiment
    onChange: (updates: {
        feature_flag_variants?: MultivariateFlagVariant[]
        ensure_experience_continuity?: boolean
        feature_flag_key?: string
        parameters?: {
            feature_flag_variants?: MultivariateFlagVariant[]
            ensure_experience_continuity?: boolean
        }
    }) => void
}

export const VariantsPanelCreateFeatureFlag = ({
    experiment,
    onChange,
}: VariantsPanelCreateFeatureFlagProps): JSX.Element => {
    const { featureFlagKeyValidation, featureFlagKeyValidationLoading } = useValues(variantsPanelLogic)
    const { setFeatureFlagKeyDirty, validateFeatureFlagKey } = useActions(variantsPanelLogic)

    const variants = experiment.parameters?.feature_flag_variants || [
        { key: 'control', rollout_percentage: 50 },
        { key: 'test', rollout_percentage: 50 },
    ]

    const ensureExperienceContinuity =
        (experiment.parameters as { ensure_experience_continuity?: boolean })?.ensure_experience_continuity ?? false

    const variantRolloutSum = variants.reduce((sum, { rollout_percentage }) => sum + rollout_percentage, 0)
    const areVariantRolloutsValid =
        variants.every(({ rollout_percentage }) => rollout_percentage >= 0 && rollout_percentage <= 100) &&
        variantRolloutSum === 100

    const areVariantKeysValid = variants.every(({ key }) => key && key.trim().length > 0)
    const variantKeys = variants.map(({ key }) => key)
    const hasDuplicateKeys = variantKeys.length !== new Set(variantKeys).size

    // Check if specific variant has an error
    const hasVariantError = (index: number): boolean => {
        const variant = variants[index]
        const isEmpty = !variant.key || variant.key.trim().length === 0
        const isDuplicate = variantKeys.filter((k) => k === variant.key).length > 1
        return isEmpty || isDuplicate
    }

    const updateVariant = (index: number, updates: Partial<MultivariateFlagVariant>): void => {
        const newVariants = [...variants]
        newVariants[index] = { ...newVariants[index], ...updates }
        onChange({
            parameters: {
                ...experiment.parameters,
                feature_flag_variants: newVariants,
                ensure_experience_continuity: ensureExperienceContinuity,
            },
        })
    }

    const addVariant = (): void => {
        if (variants.length >= MAX_EXPERIMENT_VARIANTS) {
            return
        }
        const newVariant: MultivariateFlagVariant = {
            key: `test-${variants.length}`,
            rollout_percentage: 0,
        }
        const newVariants = [...variants, newVariant]
        distributeVariantsEqually(newVariants)
    }

    const removeVariant = (index: number): void => {
        if (variants.length <= 2 || index === 0) {
            return
        }
        const newVariants = variants.filter((_, i) => i !== index)
        distributeVariantsEqually(newVariants)
    }

    const distributeVariantsEqually = (variantsToDistribute?: MultivariateFlagVariant[]): void => {
        const variantsToUse = variantsToDistribute ||
            experiment.parameters?.feature_flag_variants || [
                { key: 'control', rollout_percentage: 50 },
                { key: 'test', rollout_percentage: 50 },
            ]
        const percentages = percentageDistribution(variantsToUse.length)
        const newVariants = variantsToUse.map((variant, index) => ({
            ...variant,
            rollout_percentage: percentages[index],
        }))
        onChange({
            parameters: {
                feature_flag_variants: newVariants,
                ensure_experience_continuity: ensureExperienceContinuity,
            },
        })
    }

    const debouncedValidateFeatureFlagKey = useDebouncedCallback((key: string) => {
        if (key) {
            validateFeatureFlagKey(key)
        }
    }, 100)

    return (
        <div className="flex flex-col gap-4">
            <LemonField.Pure label="Feature flag key" htmlFor="experiment-feature-flag-key">
                <>
                    <LemonInput
                        id="experiment-feature-flag-key"
                        placeholder="examples: new-landing-page, betaFeature, ab_test_1"
                        value={experiment.feature_flag_key || ''}
                        onChange={(value) => {
                            /**
                             * if the user changes the feature flag key, we need to set the dirty flag to true
                             * so that we don't generate a new key automatically
                             * TODO: clear dirty flag when the name is empty
                             */
                            setFeatureFlagKeyDirty()
                            const normalizedValue = value.replace(/\s+/g, '-')
                            onChange({
                                feature_flag_key: normalizedValue,
                            })
                            debouncedValidateFeatureFlagKey(normalizedValue)
                        }}
                        suffix={
                            featureFlagKeyValidationLoading ? (
                                <Spinner size="small" />
                            ) : featureFlagKeyValidation?.valid ? (
                                <IconCheck className="text-success" />
                            ) : null
                        }
                        status={featureFlagKeyValidation?.error ? 'danger' : 'default'}
                    />
                    {featureFlagKeyValidation?.error && (
                        <div className="text-xs text-danger">{featureFlagKeyValidation.error}</div>
                    )}
                    <div className="text-sm text-secondary">
                        Each experiment is backed by a feature flag. This key will be used to control the experiment in
                        your code.
                    </div>
                </>
            </LemonField.Pure>

            <LemonField.Pure
                label="Variant keys"
                help="The rollout percentage of experiment variants must add up to 100%"
            >
                <div className="text-sm border border-primary rounded p-4">
                    <div className="grid grid-cols-24 gap-2 font-bold mb-2 items-center">
                        <div />
                        <div className="col-span-4">Variant key</div>
                        <div className="col-span-6">Description</div>
                        <div className="col-span-3 flex justify-between items-center gap-1">
                            <span>Rollout</span>
                            <LemonButton
                                onClick={() => distributeVariantsEqually()}
                                tooltip="Normalize variant rollout percentages"
                            >
                                <IconBalance />
                            </LemonButton>
                        </div>
                    </div>
                    {variants.map((variant, index) => (
                        <div
                            key={index}
                            className={`grid grid-cols-24 gap-2 mb-2 p-2 rounded ${
                                hasVariantError(index)
                                    ? 'bg-danger-highlight border border-danger'
                                    : 'bg-transparent border border-transparent'
                            }`}
                        >
                            <div className="flex items-center justify-center">
                                <Lettermark name={alphabet[index]} color={LettermarkColor.Gray} />
                            </div>
                            <div className="col-span-4">
                                <LemonInput
                                    value={variant.key}
                                    disabledReason={
                                        variant.key === 'control' ? 'Control variant cannot be changed' : null
                                    }
                                    onChange={(value) => updateVariant(index, { key: value.replace(/\s+/g, '-') })}
                                    data-attr="experiment-variant-key"
                                    data-key-index={index.toString()}
                                    className="ph-ignore-input"
                                    placeholder={`example-variant-${index + 1}`}
                                    autoComplete="off"
                                    autoCapitalize="off"
                                    autoCorrect="off"
                                    spellCheck={false}
                                />
                            </div>
                            <div className="col-span-6">
                                <LemonInput
                                    value={variant.name || ''}
                                    onChange={(value) => updateVariant(index, { name: value })}
                                    data-attr="experiment-variant-name"
                                    className="ph-ignore-input"
                                    placeholder="Description"
                                />
                            </div>
                            <div className="col-span-3">
                                <LemonInput
                                    type="number"
                                    min={0}
                                    max={100}
                                    value={variant.rollout_percentage}
                                    onChange={(changedValue) => {
                                        const valueInt =
                                            changedValue !== undefined && !Number.isNaN(changedValue)
                                                ? parseInt(changedValue.toString(), 10)
                                                : 0
                                        updateVariant(index, { rollout_percentage: valueInt })
                                    }}
                                    suffix={<span>%</span>}
                                    data-attr="experiment-variant-rollout-percentage-input"
                                />
                            </div>
                            <div className="flex items-center justify-center">
                                {variants.length > 2 && index > 0 && (
                                    <LemonButton
                                        icon={<IconTrash />}
                                        data-attr={`delete-prop-filter-${index}`}
                                        noPadding
                                        onClick={() => removeVariant(index)}
                                        tooltipPlacement="top-end"
                                    />
                                )}
                            </div>
                        </div>
                    ))}
                    {variants.length > 0 && !areVariantRolloutsValid && (
                        <p className="text-danger">
                            Percentage rollouts for variants must sum to 100 (currently {variantRolloutSum}).
                        </p>
                    )}
                    {variants.length > 0 && !areVariantKeysValid && (
                        <p className="text-danger">All variants must have a key.</p>
                    )}
                    {variants.length > 0 && hasDuplicateKeys && (
                        <p className="text-danger">Variant keys must be unique.</p>
                    )}
                    {variants.length < MAX_EXPERIMENT_VARIANTS && (
                        <LemonButton type="secondary" onClick={addVariant} icon={<IconPlus />} center>
                            Add variant
                        </LemonButton>
                    )}
                </div>
            </LemonField.Pure>

            <div>
                <LemonCheckbox
                    label="Persist flag across authentication steps"
                    onChange={(checked) => {
                        onChange({
                            parameters: {
                                feature_flag_variants: variants,
                                ensure_experience_continuity: checked,
                            },
                        })
                    }}
                    fullWidth
                    checked={ensureExperienceContinuity}
                />
                <div className="text-secondary text-sm pl-6 mt-2">
                    If your feature flag is evaluated for anonymous users, use this option to ensure the flag value
                    remains consistent after the user logs in. Note that this feature requires creating profiles for
                    anonymous users.
                </div>
            </div>
        </div>
    )
}
