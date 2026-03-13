import { IconBalance } from '@posthog/icons'

import { getSeriesColor } from 'lib/colors'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { alphabet, formatPercentage } from 'lib/utils'

import type { MultivariateFlagVariant } from '~/types'

import { isEvenlyDistributed, percentageDistribution } from '../utils'

interface TrafficPreviewProps {
    variants: MultivariateFlagVariant[]
    rolloutPercentage: number
    areVariantRolloutsValid: boolean
}

// Visualizes the bucketing logic performed by the backend
export const TrafficPreview = ({
    variants,
    rolloutPercentage,
    areVariantRolloutsValid,
}: TrafficPreviewProps): JSX.Element => {
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
                {excludedPercentage > 0 && (
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
                )}
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

// In case of 2 variants we can improve the UX by automatically adjusting the other variant to ensure the total is always 100%
export function computeUpdatedVariantSplit(
    variants: MultivariateFlagVariant[],
    index: number,
    value: number
): MultivariateFlagVariant[] {
    const cappedValue = Math.min(100, Math.max(0, value))
    const newVariants = [...variants]
    newVariants[index] = { ...newVariants[index], rollout_percentage: cappedValue }
    if (variants.length === 2) {
        const otherIndex = index === 0 ? 1 : 0
        newVariants[otherIndex] = { ...newVariants[otherIndex], rollout_percentage: 100 - cappedValue }
    }
    return newVariants
}

export function distributeVariantsEvenly(variants: MultivariateFlagVariant[]): MultivariateFlagVariant[] {
    const percentages = percentageDistribution(variants.length)
    return variants.map((variant, index) => ({
        ...variant,
        rollout_percentage: percentages[index],
    }))
}

/** Parse a LemonInput number value into an integer suitable for variant rollout percentages */
export function parseVariantPercentage(value: number | undefined): number {
    return value !== undefined && !Number.isNaN(value) ? parseInt(value.toString(), 10) : 0
}

interface VariantDistributionEditorProps {
    variants: MultivariateFlagVariant[]
    onVariantsChange: (variants: MultivariateFlagVariant[]) => void
    rolloutPercentage?: number
}

/**
 * Self-contained variant distribution editor with split editing, 2-variant auto-complete,
 * distribute evenly, validation, and traffic preview.
 *
 * Used by DistributionModal for changing experiment distribution, and can be embedded
 * in any context that needs variant split editing with a traffic preview.
 */
export const VariantDistributionEditor = ({
    variants,
    onVariantsChange,
    rolloutPercentage = 100,
}: VariantDistributionEditorProps): JSX.Element => {
    const { variantRolloutSum, areVariantRolloutsValid } = useVariantDistributionValidation(variants)

    return (
        <div className="flex flex-col gap-4">
            <div>
                <div className="flex justify-between items-center mb-2">
                    <h3 className="font-semibold mb-0">Variant distribution</h3>
                    <LemonButton
                        size="small"
                        onClick={() => onVariantsChange(distributeVariantsEvenly(variants))}
                        tooltip="Distribute split evenly"
                        icon={<IconBalance />}
                        className={isEvenlyDistributed(variants) ? 'invisible' : ''}
                    >
                        Distribute evenly
                    </LemonButton>
                </div>

                <div className="border border-primary rounded p-4">
                    <table className="w-full">
                        <thead>
                            <tr className="text-sm font-bold">
                                <td className="w-8" />
                                <td>Variant</td>
                                <td>Split</td>
                            </tr>
                        </thead>
                        <tbody>
                            {variants.map((variant, index) => (
                                <tr key={variant.key}>
                                    <td className="py-2 pr-2">
                                        <div className="flex items-center justify-center">
                                            <Lettermark name={alphabet[index]} color={LettermarkColor.Gray} />
                                        </div>
                                    </td>
                                    <td className="py-2 pr-2">
                                        <span className="font-semibold">{variant.key}</span>
                                    </td>
                                    <td className="py-2">
                                        <LemonInput
                                            type="number"
                                            min={0}
                                            max={100}
                                            value={variant.rollout_percentage}
                                            onChange={(changedValue) => {
                                                onVariantsChange(
                                                    computeUpdatedVariantSplit(
                                                        variants,
                                                        index,
                                                        parseVariantPercentage(changedValue)
                                                    )
                                                )
                                            }}
                                            suffix={<span>%</span>}
                                            className="w-30"
                                        />
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>

                    {!areVariantRolloutsValid && (
                        <p className="text-danger mt-2">
                            Percentage splits must sum to 100 (currently {variantRolloutSum}).
                        </p>
                    )}
                </div>
            </div>

            <TrafficPreview
                variants={variants}
                rolloutPercentage={rolloutPercentage}
                areVariantRolloutsValid={areVariantRolloutsValid}
            />
        </div>
    )
}

/** Hook exposing validation state for variant distributions */
export function useVariantDistributionValidation(variants: MultivariateFlagVariant[]): {
    variantRolloutSum: number
    areVariantRolloutsValid: boolean
} {
    const variantRolloutSum = variants.reduce((sum, { rollout_percentage }) => sum + rollout_percentage, 0)
    const areVariantRolloutsValid =
        variants.every(({ rollout_percentage }) => rollout_percentage >= 0 && rollout_percentage <= 100) &&
        variantRolloutSum === 100
    return { variantRolloutSum, areVariantRolloutsValid }
}
