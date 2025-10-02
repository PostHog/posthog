import { IconBalance } from '@posthog/icons'
import { IconTrash } from '@posthog/icons'
import { IconPlus } from '@posthog/icons'

import { MAX_EXPERIMENT_VARIANTS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { alphabet } from 'lib/utils'
import { JSONEditorInput } from 'scenes/feature-flags/JSONEditorInput'

import type { Experiment, MultivariateFlagVariant } from '~/types'

import { percentageDistribution } from '../utils'

interface VariantsPanelCreateFeatureFlagProps {
    experiment: Experiment
    onChange: (updates: {
        parameters: {
            feature_flag_variants: MultivariateFlagVariant[]
            ensure_experience_continuity?: boolean
            feature_flag_key?: string
        }
    }) => void
}

export const VariantsPanelCreateFeatureFlag = ({
    experiment,
    onChange,
}: VariantsPanelCreateFeatureFlagProps): JSX.Element => {
    const variants = experiment.parameters?.feature_flag_variants || [
        { key: 'control', rollout_percentage: 50 },
        { key: 'test', rollout_percentage: 50 },
    ]

    const ensureExperienceContinuity =
        (experiment.parameters as { ensure_experience_continuity?: boolean })?.ensure_experience_continuity ?? true

    const variantRolloutSum = variants.reduce((sum, { rollout_percentage }) => sum + rollout_percentage, 0)
    const areVariantRolloutsValid =
        variants.every(({ rollout_percentage }) => rollout_percentage >= 0 && rollout_percentage <= 100) &&
        variantRolloutSum === 100

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

    return (
        <div>
            <div className="max-w-2xl mb-4">
                <label htmlFor="experiment-feature-flag-key" className="text-sm font-semibold">
                    Feature flag key
                </label>
                <LemonInput
                    className="mt-1"
                    placeholder="pricing-page-conversion"
                    data-attr="experiment-feature-flag-key"
                    value={experiment.feature_flag_key || ''}
                    onChange={(value) => {
                        onChange({
                            parameters: {
                                feature_flag_variants: variants,
                                ensure_experience_continuity: ensureExperienceContinuity,
                                feature_flag_key: value,
                            },
                        })
                    }}
                    onFocus={() => {
                        if (!experiment.feature_flag_key && experiment.name) {
                            onChange({
                                parameters: {
                                    feature_flag_variants: variants,
                                    ensure_experience_continuity: ensureExperienceContinuity,
                                },
                            })
                        }
                    }}
                />
                <div className="text-xs text-muted mt-1">
                    Each experiment is backed by a feature flag. This key will be used to control the experiment in your
                    code.
                </div>
            </div>

            <h3 className="font-semibold mb-2">Variant keys</h3>
            <div className="text-sm text-muted mb-4">
                The rollout percentage of feature flag variants must add up to 100%
            </div>

            <div className="p-4 mt-4 text-sm border border-primary rounded">
                <div className="grid grid-cols-24 gap-2 font-bold mb-2">
                    <div />
                    <div className="col-span-4">Variant key</div>
                    <div className="col-span-6">Description</div>
                    <div className="col-span-8">
                        <div className="flex flex-col">
                            <span>Payload</span>
                            <span className="text-secondary font-normal">
                                Specify return payload when the variant key matches
                            </span>
                        </div>
                    </div>
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
                    <div key={variant.key} className="grid grid-cols-24 gap-2 mb-2">
                        <div className="flex items-center justify-center">
                            <Lettermark name={alphabet[index]} color={LettermarkColor.Gray} />
                        </div>
                        <div className="col-span-4">
                            <LemonInput
                                value={variant.key}
                                onChange={(value) => updateVariant(index, { key: value })}
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
                        <div className="col-span-8">
                            <JSONEditorInput
                                onChange={(newValue) => {
                                    const updatedVariant = { ...variant, name: newValue }
                                    if (newValue === '') {
                                        delete updatedVariant.name
                                    } else {
                                        updatedVariant.name = newValue
                                    }
                                    updateVariant(index, updatedVariant)
                                }}
                                value={variant.name || ''}
                                placeholder='{"key": "value"}'
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
                {variants.length < MAX_EXPERIMENT_VARIANTS && (
                    <LemonButton type="secondary" onClick={addVariant} icon={<IconPlus />} center>
                        Add variant
                    </LemonButton>
                )}
            </div>

            <div className="max-w-2xl mt-4">
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
