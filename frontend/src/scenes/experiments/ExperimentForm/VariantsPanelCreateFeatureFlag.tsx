import { useValues } from 'kea'
import { Fragment, ReactNode, RefCallback, RefObject, useState } from 'react'

import { IconBalance, IconChevronDown, IconInfo, IconPencil, IconPlus, IconTrash } from '@posthog/icons'

import { MAX_EXPERIMENT_VARIANTS } from 'lib/constants'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { formatPercentage } from 'lib/utils/numbers'
import { alphabet } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'

import type { Experiment, MultivariateFlagVariant } from '~/types'

import { NEW_EXPERIMENT } from 'products/experiments/frontend/constants'

import { ensureIsPercent, isEvenlyDistributed } from '../utils'
import { PersistFlagAcrossAuthentication } from './PersistFlagAcrossAuthentication'
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
        feature_flag_key?: string
        variants?: MultivariateFlagVariant[]
        rollout_percentage?: number
        ensure_experience_continuity?: boolean
    }) => void
    disabled?: boolean
    layout?: 'horizontal' | 'vertical'
    /** Extra columns in the variants table after "Split", e.g. screenshots and notes */
    extraVariantColumns?: VariantColumn[]
}

export interface VariantColumn {
    key: string
    title: ReactNode
    render: (variant: MultivariateFlagVariant, index: number) => ReactNode
    className?: string
    /** When the table is narrow, columns are added from a menu under the variant, e.g. "Add note" */
    menuLabel: string
    /** Whether the variant already has a value, so the column shows without picking it from the menu */
    hasValue: (variant: MultivariateFlagVariant) => boolean
    /** Whether the column applies to the variant at all, e.g. not before it has a key */
    isAvailable?: (variant: MultivariateFlagVariant) => boolean
}

const EQUAL_SPLIT_ADVICE =
    'We recommend an equal split between variants. The less traffic a variant gets, the longer it takes to reach reliable results.'

// Below this width (px) extra columns won't fit beside the key and split, so they move to a line under each variant
const VARIANT_TABLE_BREAKPOINTS = { 0: 'stacked', 560: 'inline' } as const

/** Splits extra variant columns into inline table columns or a stacked line, based on the table's own width */
export function useVariantColumnsLayout(columns: VariantColumn[]): {
    ref: RefCallback<HTMLDivElement> | RefObject<HTMLDivElement> | undefined
    inlineColumns: VariantColumn[]
    stackedColumns: VariantColumn[]
} {
    const { ref, size } = useResizeBreakpoints(VARIANT_TABLE_BREAKPOINTS, { initialSize: 'inline' })
    return {
        ref,
        inlineColumns: size === 'inline' ? columns : [],
        stackedColumns: size === 'stacked' ? columns : [],
    }
}

/**
 * When the table is too narrow for extra columns, they go under the variant's row instead. Each one is added
 * from a menu and shown with its title as a label, so it's clear what the field is. Columns that already have
 * a value show straight away.
 */
export function StackedVariantColumnsRow({
    columns,
    variant,
    index,
    colSpan,
}: {
    columns: VariantColumn[]
    variant: MultivariateFlagVariant
    index: number
    colSpan: number
}): JSX.Element | null {
    const [addedKeys, setAddedKeys] = useState<string[]>([])

    const available = columns.filter((column) => column.isAvailable?.(variant) ?? true)
    if (available.length === 0) {
        return null
    }
    const shown = available.filter((column) => addedKeys.includes(column.key) || column.hasValue(variant))
    const notShown = available.filter((column) => !shown.includes(column))
    const add = (key: string): void => setAddedKeys((keys) => [...keys, key])

    return (
        <tr>
            <td />
            <td colSpan={colSpan} className="pb-2">
                <div className="flex flex-col items-start gap-2">
                    {shown.map((column) => (
                        <div key={column.key} className="flex flex-col gap-1 w-full">
                            <span className="text-xs font-semibold text-secondary">{column.title}</span>
                            {column.render(variant, index)}
                        </div>
                    ))}
                    {notShown.length === 1 ? (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            icon={<IconPlus />}
                            onClick={() => add(notShown[0].key)}
                            data-attr="experiment-variant-add-detail"
                        >
                            {notShown[0].menuLabel}
                        </LemonButton>
                    ) : notShown.length > 1 ? (
                        <LemonMenu
                            items={notShown.map((column) => ({
                                label: column.menuLabel,
                                onClick: () => add(column.key),
                            }))}
                        >
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                icon={<IconPlus />}
                                sideIcon={<IconChevronDown />}
                                data-attr="experiment-variant-add-detail"
                            >
                                Add screenshot or note
                            </LemonButton>
                        </LemonMenu>
                    ) : null}
                </div>
            </td>
        </tr>
    )
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
    extraVariantColumns = [],
}: VariantsPanelCreateFeatureFlagProps): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)
    const [isCustomSplit, setIsCustomSplit] = useState(false)
    const { ref: variantsTableRef, inlineColumns, stackedColumns } = useVariantColumnsLayout(extraVariantColumns)

    const filters = experiment.feature_flag_config?.filters
    const variants: MultivariateFlagVariant[] = filters?.multivariate?.variants ?? [
        { key: 'control', rollout_percentage: 50 },
        { key: 'test', rollout_percentage: 50 },
    ]

    // Unset until someone chooses. Other edits pass it through unset, so the persist question can tell. An unset
    // value saves the team's default, which is what's shown here.
    const ensureExperienceContinuityChoice = experiment.feature_flag_config?.ensure_experience_continuity ?? undefined
    const ensureExperienceContinuity =
        ensureExperienceContinuityChoice ?? currentTeam?.flags_persistence_default ?? false

    const rolloutPercentage =
        filters?.groups?.[0]?.rollout_percentage ??
        NEW_EXPERIMENT.feature_flag_config?.filters?.groups?.[0]?.rollout_percentage ??
        100

    const updateRolloutPercentage = (value: number): void => {
        onChange({
            variants,
            ensure_experience_continuity: ensureExperienceContinuityChoice,
            rollout_percentage: value,
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
            variants: newVariants,
            ensure_experience_continuity: ensureExperienceContinuityChoice,
            rollout_percentage: rolloutPercentage,
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

                <div className="flex-1">
                    <LemonField.Pure label="Variants">
                        <div className="border border-primary rounded p-4" ref={variantsTableRef}>
                            {!disabled && !isEvenlyDistributed(variants) && (
                                <LemonBanner type="warning" className="mb-3">
                                    In most cases, experiments work best with an equal split. If you want to limit
                                    exposure to the test variant, adjust the rollout percentage instead.
                                </LemonBanner>
                            )}
                            <table className="w-full">
                                <thead>
                                    <tr className="text-sm font-bold">
                                        <td className="w-8" />
                                        <td>Variant key</td>
                                        <td>
                                            <div className="flex items-center gap-1">
                                                <span>Split</span>
                                                <Tooltip
                                                    title={EQUAL_SPLIT_ADVICE}
                                                    docLink="https://posthog.com/docs/experiments/traffic-allocation"
                                                >
                                                    <IconInfo className="text-secondary text-base" />
                                                </Tooltip>
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
                                        {inlineColumns.map((column) => (
                                            <td key={column.key} className={column.className}>
                                                {column.title}
                                            </td>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {variants.map((variant, index) => (
                                        <Fragment key={index}>
                                            <tr
                                                className={
                                                    hasVariantError(index)
                                                        ? 'bg-danger-highlight border border-danger'
                                                        : ''
                                                }
                                            >
                                                <td className="py-2 pr-2">
                                                    <div className="flex items-center justify-center">
                                                        <Lettermark
                                                            name={alphabet[index]}
                                                            color={LettermarkColor.Gray}
                                                        />
                                                    </div>
                                                </td>
                                                <td
                                                    className={`py-2 pr-2 ${inlineColumns.length > 0 ? 'min-w-36' : ''}`}
                                                >
                                                    <LemonInput
                                                        value={variant.key}
                                                        disabledReason={
                                                            disabled
                                                                ? 'Cannot edit feature flag in edit mode'
                                                                : experiment.type === 'web' && variant.key === 'control'
                                                                  ? "Web experiments require a variant with key 'control'"
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
                                                            // Same size as the split input, so toggling "Customize split"
                                                            // doesn't resize the row or reflow the table's columns
                                                            <div className="flex items-center h-[calc(2.125rem+3px)] w-30 px-2">
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
                                                {inlineColumns.map((column) => (
                                                    <td
                                                        key={column.key}
                                                        className={`py-2 pl-2 ${column.className ?? ''}`}
                                                    >
                                                        {column.render(variant, index)}
                                                    </td>
                                                ))}
                                            </tr>
                                            <StackedVariantColumnsRow
                                                columns={stackedColumns}
                                                variant={variant}
                                                index={index}
                                                colSpan={2}
                                            />
                                        </Fragment>
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
            </div>

            <PersistFlagAcrossAuthentication
                checked={ensureExperienceContinuity}
                answered={ensureExperienceContinuityChoice !== undefined}
                onChange={(checked) => {
                    onChange({
                        variants,
                        ensure_experience_continuity: checked,
                        rollout_percentage: rolloutPercentage,
                    })
                }}
                disabledReason={
                    disabled
                        ? 'You cannot change the persist flag across authentication steps when editing an experiment.'
                        : undefined
                }
            />
        </div>
    )
}
