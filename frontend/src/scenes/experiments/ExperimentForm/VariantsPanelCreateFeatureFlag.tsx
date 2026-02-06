import { useState } from 'react'

import { IconBalance, IconPencil, IconPlus, IconTrash } from '@posthog/icons'

import { MAX_EXPERIMENT_VARIANTS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { Link } from 'lib/lemon-ui/Link/Link'
import { alphabet } from 'lib/utils'

import type { Experiment, MultivariateFlagVariant } from '~/types'

import { isEvenlyDistributed, percentageDistribution } from '../utils'

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
    disabled?: boolean
}

export const VariantsPanelCreateFeatureFlag = ({
    experiment,
    onChange,
    disabled = false,
}: VariantsPanelCreateFeatureFlagProps): JSX.Element => {
    const [isCustomSplit, setIsCustomSplit] = useState(false)

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

    return (
        <div className="flex flex-col gap-4">
            <LemonField.Pure label="Variants">
                <div className="border border-primary rounded p-4">
                    <table className="w-full">
                        <thead>
                            <tr className="text-sm font-bold">
                                <td className="w-5" />
                                <td className="w-20">Variant key</td>
                                <td className="w-10">
                                    <div className="flex items-center gap-1">
                                        <span>Split</span>
                                        {!disabled && (
                                            <>
                                                <LemonButton
                                                    onClick={() => setIsCustomSplit(!isCustomSplit)}
                                                    tooltip="Customize split"
                                                >
                                                    <IconPencil />
                                                </LemonButton>
                                                <LemonButton
                                                    onClick={() => distributeVariantsEqually()}
                                                    tooltip="Distribute split evenly"
                                                    className={isEvenlyDistributed(variants) ? 'invisible' : ''}
                                                >
                                                    <IconBalance />
                                                </LemonButton>
                                            </>
                                        )}
                                    </div>
                                </td>
                                <td className="w-65" />
                            </tr>
                        </thead>
                        <tbody>
                            {variants.map((variant, index) => (
                                <tr
                                    key={index}
                                    className={hasVariantError(index) ? 'bg-danger-highlight border border-danger' : ''}
                                >
                                    <td className="py-2">
                                        <div className="flex items-center justify-center">
                                            <Lettermark name={alphabet[index]} color={LettermarkColor.Gray} />
                                        </div>
                                    </td>
                                    <td className="py-2 pr-2">
                                        <LemonInput
                                            value={variant.key}
                                            disabledReason={
                                                disabled
                                                    ? 'Cannot edit feature flag in edit mode'
                                                    : variant.key === 'control'
                                                      ? 'Control variant cannot be changed'
                                                      : null
                                            }
                                            onChange={(value) =>
                                                updateVariant(index, { key: value.replace(/\s+/g, '-') })
                                            }
                                            data-attr="experiment-variant-key"
                                            data-key-index={index.toString()}
                                            className="ph-ignore-input"
                                            placeholder={`example-variant-${index + 1}`}
                                            autoComplete="off"
                                            autoCapitalize="off"
                                            autoCorrect="off"
                                            spellCheck={false}
                                        />
                                    </td>
                                    <td className="py-2">
                                        {isCustomSplit && !disabled ? (
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
                                                className="w-30"
                                            />
                                        ) : (
                                            <div className="flex items-center h-10 px-2">
                                                {variant.rollout_percentage}%
                                            </div>
                                        )}
                                    </td>
                                    <td className="py-2">
                                        <div className="flex items-center justify-center">
                                            {!disabled && variants.length > 2 && index > 0 && (
                                                <LemonButton
                                                    icon={<IconTrash />}
                                                    data-attr={`delete-prop-filter-${index}`}
                                                    noPadding
                                                    onClick={() => removeVariant(index)}
                                                    tooltipPlacement="top-end"
                                                />
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {variants.length > 0 && !areVariantRolloutsValid && (
                        <p className="text-danger mt-2">
                            Variant splits must sum to 100 (currently {variantRolloutSum}).
                        </p>
                    )}
                    {variants.length > 0 && !areVariantKeysValid && (
                        <p className="text-danger mt-2">All variants must have a key.</p>
                    )}
                    {variants.length > 0 && hasDuplicateKeys && (
                        <p className="text-danger mt-2">Variant keys must be unique.</p>
                    )}
                    {!disabled && variants.length < MAX_EXPERIMENT_VARIANTS && (
                        <LemonButton type="secondary" onClick={addVariant} icon={<IconPlus />} className="mt-2">
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
                    disabledReason={
                        disabled
                            ? 'You cannot change the persist flag across authentication steps when editing an experiment.'
                            : undefined
                    }
                />
                <div className="text-secondary text-sm pl-6 mt-2">
                    This is only relevant if your feature flag is shown to both logged out AND logged in users.{' '}
                    <Link
                        to="https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps"
                        target="_blank"
                    >
                        Learn more
                    </Link>
                </div>
            </div>
        </div>
    )
}
