import { useState } from 'react'

import { IconBalance, IconInfo, IconPencil, IconPlus, IconTrash } from '@posthog/icons'

import { MAX_EXPERIMENT_VARIANTS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { Link } from 'lib/lemon-ui/Link/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { alphabet, formatPercentage } from 'lib/utils'

import type { Experiment, MultivariateFlagVariant } from '~/types'

import { NEW_EXPERIMENT } from '../constants'
import { ensureIsPercent, isEvenlyDistributed } from '../utils'
import {
    computeUpdatedVariantSplit,
    distributeVariantsEvenly,
    parseVariantPercentage,
    TrafficPreview,
    useVariantDistributionValidation,
} from './VariantDistributionEditor'

interface VariantsPanelCreateFeatureFlagProps {
    experiment: Experiment
    onChange: (updates: {
        feature_flag_variants?: MultivariateFlagVariant[]
        ensure_experience_continuity?: boolean
        feature_flag_key?: string
        parameters?: {
            feature_flag_variants?: MultivariateFlagVariant[]
            ensure_experience_continuity?: boolean
            rollout_percentage?: number
        }
    }) => void
    disabled?: boolean
    layout?: 'horizontal' | 'vertical'
}

interface RolloutPercentageControlProps {
    rolloutPercentage: number
    disabled: boolean
    onChange: (value: number) => void
}

const RolloutPercentageControl = ({
    rolloutPercentage,
    disabled,
    onChange,
}: RolloutPercentageControlProps): JSX.Element => {
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-1">
                    <h4 className="m-0">Rollout percent</h4>
                    <Tooltip title="Percentage of users who this experiment will be released to.">
                        <IconInfo className="text-secondary text-base" />
                    </Tooltip>
                </div>
                <LemonInput
                    type="number"
                    min={0}
                    max={100}
                    value={rolloutPercentage}
                    onChange={(value) => onChange(ensureIsPercent(value))}
                    suffix={<span>%</span>}
                    disabledReason={disabled ? 'Cannot edit rollout percentage in edit mode' : undefined}
                    data-attr="experiment-rollout-percentage-input"
                    className="w-24"
                />
            </div>
            <div className={disabled ? 'pointer-events-none opacity-50' : ''}>
                <LemonSlider value={rolloutPercentage} onChange={onChange} min={0} max={100} step={1} />
            </div>
        </div>
    )
}

export const VariantsPanelCreateFeatureFlag = ({
    experiment,
    onChange,
    disabled = false,
    layout = 'horizontal',
}: VariantsPanelCreateFeatureFlagProps): JSX.Element => {
    const [isCustomSplit, setIsCustomSplit] = useState(false)

    const variants = experiment.parameters?.feature_flag_variants || [
        { key: 'control', rollout_percentage: 50 },
        { key: 'test', rollout_percentage: 50 },
    ]

    const ensureExperienceContinuity =
        (experiment.parameters as { ensure_experience_continuity?: boolean })?.ensure_experience_continuity ?? false

    const rolloutPercentage =
        experiment.parameters?.rollout_percentage ?? NEW_EXPERIMENT.parameters.rollout_percentage ?? 100

    const updateRolloutPercentage = (value: number): void => {
        onChange({
            parameters: {
                feature_flag_variants: variants,
                ensure_experience_continuity: ensureExperienceContinuity,
                rollout_percentage: value,
            },
        })
    }

    const { variantRolloutSum, areVariantRolloutsValid } = useVariantDistributionValidation(variants)

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
        updateVariants(newVariants)
    }

    const updateVariants = (newVariants: MultivariateFlagVariant[]): void => {
        onChange({
            parameters: {
                ...experiment.parameters,
                feature_flag_variants: newVariants,
                ensure_experience_continuity: ensureExperienceContinuity,
                rollout_percentage: rolloutPercentage,
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
        updateVariants(distributeVariantsEvenly([...variants, newVariant]))
    }

    const removeVariant = (index: number): void => {
        if (variants.length <= 2 || index === 0) {
            return
        }
        updateVariants(distributeVariantsEvenly(variants.filter((_, i) => i !== index)))
    }

    return (
        <div className="flex flex-col gap-4">
            <div className={`flex gap-4 ${layout === 'vertical' ? 'flex-col' : 'flex-row'}`}>
                <div className="flex-1">
                    <LemonField.Pure label="Variants">
                        <div className="border border-primary rounded p-4">
                            <table className="w-full">
                                <thead>
                                    <tr className="text-sm font-bold">
                                        <td className="w-8" />
                                        <td>Variant key</td>
                                        <td>
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
                                                            onClick={() =>
                                                                updateVariants(distributeVariantsEvenly(variants))
                                                            }
                                                            tooltip="Distribute split evenly"
                                                            data-attr="distribute-variants-equally"
                                                            className={isEvenlyDistributed(variants) ? 'invisible' : ''}
                                                        >
                                                            <IconBalance />
                                                        </LemonButton>
                                                    </>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                </thead>
                                <tbody>
                                    {variants.map((variant, index) => (
                                        <tr
                                            key={index}
                                            className={
                                                hasVariantError(index) ? 'bg-danger-highlight border border-danger' : ''
                                            }
                                        >
                                            <td className="py-2 pr-2">
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
                                                <div className="flex items-center gap-1">
                                                    {isCustomSplit && !disabled ? (
                                                        <LemonInput
                                                            type="number"
                                                            min={0}
                                                            max={100}
                                                            value={variant.rollout_percentage}
                                                            onChange={(changedValue) => {
                                                                updateVariants(
                                                                    computeUpdatedVariantSplit(
                                                                        variants,
                                                                        index,
                                                                        parseVariantPercentage(changedValue)
                                                                    )
                                                                )
                                                            }}
                                                            suffix={<span>%</span>}
                                                            data-attr="experiment-variant-rollout-percentage-input"
                                                            className="w-30"
                                                        />
                                                    ) : (
                                                        <div className="flex items-center h-10 px-2">
                                                            {formatPercentage(variant.rollout_percentage, {
                                                                compact: true,
                                                            })}
                                                        </div>
                                                    )}
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
                </div>

                <div className="flex-1">
                    <LemonField.Pure label="Rollout">
                        <div className="border border-primary rounded p-4 flex flex-col gap-5">
                            <RolloutPercentageControl
                                rolloutPercentage={rolloutPercentage}
                                disabled={disabled}
                                onChange={updateRolloutPercentage}
                            />
                            <TrafficPreview
                                variants={variants}
                                rolloutPercentage={rolloutPercentage}
                                areVariantRolloutsValid={areVariantRolloutsValid}
                            />
                        </div>
                    </LemonField.Pure>
                </div>
            </div>

            <div>
                <LemonCheckbox
                    label="Persist flag across authentication steps"
                    onChange={(checked) => {
                        onChange({
                            parameters: {
                                feature_flag_variants: variants,
                                ensure_experience_continuity: checked,
                                rollout_percentage: rolloutPercentage,
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
                    This is only relevant if your feature flag is shown to both logged out AND logged in users. Note
                    that this feature is not compatible with all setups,{' '}
                    <Link
                        to="https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps"
                        target="_blank"
                    >
                        learn more
                    </Link>
                </div>
            </div>
        </div>
    )
}
