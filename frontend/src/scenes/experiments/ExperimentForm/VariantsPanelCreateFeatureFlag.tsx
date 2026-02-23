import { useState } from 'react'

import { IconBalance, IconInfo, IconPencil, IconPlus, IconTrash } from '@posthog/icons'

import { getSeriesColor } from 'lib/colors'
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
import { ensureIsPercent, isEvenlyDistributed, percentageDistribution } from '../utils'

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
                    className="w-20"
                />
            </div>
            <div className={disabled ? 'pointer-events-none opacity-50' : ''}>
                <LemonSlider value={rolloutPercentage} onChange={onChange} min={0} max={100} step={1} />
            </div>
        </div>
    )
}

interface TrafficPreviewProps {
    variants: MultivariateFlagVariant[]
    rolloutPercentage: number
    areVariantRolloutsValid: boolean
}

// Visualizes the bucketing logic performed by the backend
const TrafficPreview = ({ variants, rolloutPercentage, areVariantRolloutsValid }: TrafficPreviewProps): JSX.Element => {
    const excludedPercentage = Math.max(0, 100 - rolloutPercentage)

    let cumulativeStart = 0
    const previewVariants = variants.map((variant, index) => {
        const slotSize = variant.rollout_percentage
        const slotStart = cumulativeStart
        cumulativeStart += slotSize
        return {
            ...variant,
            index,
            letter: alphabet[index] ?? `${index + 1}`,
            slotSize,
            slotStart,
            previewPercentage: Math.max(0, (variant.rollout_percentage / 100) * rolloutPercentage),
            color: getSeriesColor(index),
        }
    })

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
                <h4 className="m-0">Traffic preview</h4>
                <div className="flex items-center gap-2 text-sm text-secondary">
                    <span
                        className="inline-block h-3 w-3 rounded-sm border border-primary"
                        style={{
                            backgroundImage:
                                'repeating-linear-gradient(45deg, var(--color-bg-3000) 0 6px, var(--border-3000) 6px 12px)',
                        }}
                    />
                    <span>
                        Not released to {formatPercentage(excludedPercentage, { precise: true, compact: true })}
                    </span>
                </div>
            </div>
            <div className="h-10 rounded bg-fill-secondary border border-primary overflow-hidden flex relative">
                {rolloutPercentage > 0 ? (
                    previewVariants.map((variant) => (
                        <div key={variant.key} className="h-full flex" style={{ width: `${variant.slotSize}%` }}>
                            <div
                                className="h-full"
                                style={{
                                    width: `${rolloutPercentage}%`,
                                    backgroundColor: variant.color,
                                }}
                            />
                            {rolloutPercentage < 100 && (
                                <div
                                    className="h-full flex-1"
                                    style={{
                                        backgroundImage:
                                            'repeating-linear-gradient(45deg, var(--color-bg-3000) 0 6px, var(--border-3000) 6px 12px)',
                                    }}
                                />
                            )}
                        </div>
                    ))
                ) : (
                    <div
                        className="h-full w-full"
                        style={{
                            backgroundImage:
                                'repeating-linear-gradient(45deg, var(--color-bg-3000) 0 6px, var(--border-3000) 6px 12px)',
                        }}
                    />
                )}
                {rolloutPercentage > 0 &&
                    previewVariants.map((variant) => (
                        <div
                            key={`${variant.key}-letter`}
                            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 text-[10px] font-semibold text-white pointer-events-none"
                            style={{
                                left: `${variant.slotStart + (variant.slotSize * rolloutPercentage) / 100 / 2}%`,
                                textShadow: '0 1px 2px rgba(0, 0, 0, 0.35)',
                            }}
                        >
                            {variant.letter}
                        </div>
                    ))}
            </div>
            <div className="flex" style={{ visibility: rolloutPercentage > 0 ? 'visible' : 'hidden' }}>
                {previewVariants.map((variant) => (
                    <div key={`${variant.key}-label`} className="flex" style={{ width: `${variant.slotSize}%` }}>
                        <div
                            className="text-xs text-secondary text-center whitespace-nowrap"
                            style={{ width: `${rolloutPercentage}%` }}
                        >
                            {formatPercentage(variant.previewPercentage, { precise: true, compact: true })}
                        </div>
                    </div>
                ))}
            </div>
            {!areVariantRolloutsValid && (
                <p className="text-danger m-0">Preview is based on the current split and rollout percentage.</p>
            )}
        </div>
    )
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

    // In case of 2 variants we can improve the UX by automatically adjusting the other variant to ensure the total is always 100%
    const updateVariantSplit = (index: number, value: number): void => {
        const cappedValue = Math.min(100, Math.max(0, value))
        if (variants.length === 2) {
            const otherIndex = index === 0 ? 1 : 0
            const newVariants = [...variants]
            newVariants[index] = { ...newVariants[index], rollout_percentage: cappedValue }
            newVariants[otherIndex] = { ...newVariants[otherIndex], rollout_percentage: 100 - cappedValue }
            updateVariants(newVariants)
        } else {
            updateVariant(index, { rollout_percentage: cappedValue })
        }
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
                rollout_percentage: rolloutPercentage,
            },
        })
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="flex gap-4">
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
                                                                const valueInt =
                                                                    changedValue !== undefined &&
                                                                    !Number.isNaN(changedValue)
                                                                        ? parseInt(changedValue.toString(), 10)
                                                                        : 0
                                                                updateVariantSplit(index, valueInt)
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
