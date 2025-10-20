import 'kea'

import { IconBalance, IconPlus, IconRewindPlay, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { alphabet } from 'lib/utils'
import { JSONEditorInput } from 'scenes/feature-flags/JSONEditorInput'

import { FeatureFlagGroupType, MultivariateFlagVariant } from '~/types'

import { VariantError } from './featureFlagLogic'

export interface FeatureFlagVariantsFormProps {
    variants: MultivariateFlagVariant[]
    payloads?: Record<string, any>
    filterGroups?: FeatureFlagGroupType[]
    onAddVariant?: () => void
    onRemoveVariant?: (index: number) => void
    onDistributeEqually?: () => void
    canEditVariant?: (index: number) => boolean
    hasExperiment?: boolean
    isDraftExperiment?: boolean
    readOnly?: boolean
    onViewRecordings?: (variantKey: string) => void
    onVariantChange?: (index: number, field: 'key' | 'name' | 'rollout_percentage', value: any) => void
    onPayloadChange?: (index: number, value: any) => void
    variantErrors: VariantError[]
}

export function focusVariantKeyField(index: number): void {
    setTimeout(
        () => document.querySelector<HTMLElement>(`.VariantFormList input[data-key-index="${index}"]`)?.focus(),
        50
    )
}

export function FeatureFlagVariantsForm({
    variants,
    payloads = {},
    filterGroups = [],
    onAddVariant,
    onRemoveVariant,
    onDistributeEqually,
    canEditVariant = () => true,
    hasExperiment = false,
    isDraftExperiment = false,
    readOnly = false,
    onViewRecordings,
    onVariantChange,
    onPayloadChange,
    variantErrors,
}: FeatureFlagVariantsFormProps): JSX.Element {
    const variantRolloutSum = variants.reduce((sum, variant) => sum + (variant.rollout_percentage || 0), 0)
    const areVariantRolloutsValid = variantRolloutSum === 100

    function variantConcatWithPunctuation(phrases: string[]): string {
        if (phrases === null || phrases.length < 3) {
            return phrases.join(' and ')
        }
        return `${phrases[0]} and ${phrases.length - 1} more sets`
    }

    if (readOnly) {
        return (
            <div className="border rounded p-4 bg-surface-primary">
                <div className="grid grid-cols-10 gap-4 font-semibold">
                    <div className="col-span-2">Key</div>
                    <div className="col-span-2">Description</div>
                    <div className="col-span-2">Payload</div>
                    <div>Rollout</div>
                    {onViewRecordings && <div className="col-span-2" />}
                </div>
                <LemonDivider className="my-3" />
                {variants.map((variant: MultivariateFlagVariant, index: number) => (
                    <div key={index}>
                        <div className="grid grid-cols-10 gap-4">
                            <div className="col-span-2">
                                <Lettermark name={alphabet[index]} color={LettermarkColor.Gray} />
                                <CopyToClipboardInline
                                    tooltipMessage={null}
                                    description="key"
                                    style={{
                                        marginLeft: '0.5rem',
                                    }}
                                    iconStyle={{ color: 'var(--color-text-secondary)' }}
                                >
                                    {variant.key}
                                </CopyToClipboardInline>
                            </div>
                            <div className="col-span-2">
                                <span className={variant.name ? '' : 'text-muted'}>
                                    {variant.name || 'There is no description for this variant key'}
                                </span>
                            </div>
                            <div className="col-span-2">
                                {payloads[index] ? (
                                    <JSONEditorInput readOnly={true} value={payloads[index]} />
                                ) : (
                                    <span className="text-secondary">No payload associated with this variant</span>
                                )}
                            </div>
                            <div>{variant.rollout_percentage}%</div>
                            {onViewRecordings && (
                                <div className="col-span-2">
                                    <LemonButton
                                        size="xsmall"
                                        icon={<IconRewindPlay />}
                                        type="secondary"
                                        onClick={() => onViewRecordings(variant.key)}
                                    >
                                        View recordings
                                    </LemonButton>
                                </div>
                            )}
                        </div>
                        {index !== variants.length - 1 && <LemonDivider className="my-3" />}
                    </div>
                ))}
            </div>
        )
    }

    return (
        <div className="VariantFormList deprecated-space-y-2 mt-0">
            <div className="VariantFormList__row grid label-row gap-2 items-center">
                <div />
                <div className="col-span-4">Variant key</div>
                <div className="col-span-6">Description</div>
                <div className="col-span-8">
                    <div className="flex flex-col">
                        <b>Payload</b>
                        <span className="text-secondary font-normal">
                            Specify return payload when the variant key matches
                        </span>
                    </div>
                </div>
                <div className="col-span-3 flex justify-between items-center gap-1">
                    <span>Rollout</span>
                    {onDistributeEqually && (
                        <LemonButton onClick={onDistributeEqually} tooltip="Normalize variant rollout percentages">
                            <IconBalance />
                        </LemonButton>
                    )}
                </div>
            </div>
            {variants.map((variant: MultivariateFlagVariant, index: number) => (
                <div key={index} className="VariantFormList__row grid gap-2">
                    <div className="flex mt-2 justify-center">
                        <Lettermark name={alphabet[index]} color={LettermarkColor.Gray} />
                    </div>
                    <div className="col-span-4">
                        <LemonField.Pure error={variantErrors[index]?.key}>
                            <LemonInput
                                data-attr="feature-flag-variant-key"
                                data-key-index={index.toString()}
                                className="ph-ignore-input"
                                placeholder={`example-variant-${index + 1}`}
                                autoComplete="off"
                                autoCapitalize="off"
                                autoCorrect="off"
                                spellCheck={false}
                                disabled={!canEditVariant(index)}
                                value={variant.key}
                                onChange={(value) => onVariantChange?.(index, 'key', value)}
                            />
                        </LemonField.Pure>
                    </div>
                    <div className="col-span-6">
                        <LemonInput
                            data-attr="feature-flag-variant-name"
                            className="ph-ignore-input"
                            placeholder="Description"
                            value={variant.name || ''}
                            onChange={(value) => onVariantChange?.(index, 'name', value)}
                        />
                    </div>
                    <div className="col-span-8">
                        <JSONEditorInput
                            onChange={(newValue) => {
                                onPayloadChange?.(index, newValue === '' ? undefined : newValue)
                            }}
                            value={payloads[index]}
                            placeholder='{"key": "value"}'
                        />
                    </div>
                    <div className="col-span-3">
                        <div>
                            <LemonInput
                                type="number"
                                min={0}
                                max={100}
                                value={variant.rollout_percentage || 0}
                                onChange={(changedValue) => {
                                    const valueInt =
                                        changedValue !== undefined && !isNaN(Number(changedValue))
                                            ? parseInt(changedValue.toString())
                                            : 0

                                    onVariantChange?.(index, 'rollout_percentage', valueInt)
                                }}
                                suffix={<span>%</span>}
                                data-attr="feature-flag-variant-rollout-percentage-input"
                            />
                            {filterGroups.filter((group) => group.variant === variant.key).length > 0 && (
                                <span className="text-secondary text-xs">
                                    Overridden by{' '}
                                    <strong>
                                        {variantConcatWithPunctuation(
                                            filterGroups
                                                .filter(
                                                    (group) => group.variant != null && group.variant === variant.key
                                                )
                                                .map(
                                                    (variant) =>
                                                        'Set ' +
                                                        (filterGroups.findIndex((group) => group === variant) + 1)
                                                )
                                        )}
                                    </strong>
                                </span>
                            )}
                        </div>
                    </div>
                    <div className="flex justify-center items-start mt-1.5">
                        {variants.length > 1 && onRemoveVariant && (
                            <LemonButton
                                icon={<IconTrash />}
                                data-attr={`delete-prop-filter-${index}`}
                                noPadding
                                onClick={() => onRemoveVariant(index)}
                                disabledReason={
                                    !canEditVariant(index)
                                        ? isDraftExperiment
                                            ? 'Cannot delete the control variant from an experiment.'
                                            : 'Cannot delete variants from a feature flag that is part of a launched experiment.'
                                        : undefined
                                }
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
            {onAddVariant && (
                <LemonButton
                    type="secondary"
                    onClick={() => {
                        const newIndex = variants.length
                        onAddVariant()
                        focusVariantKeyField(newIndex)
                    }}
                    icon={<IconPlus />}
                    disabledReason={
                        hasExperiment && !isDraftExperiment
                            ? 'Cannot add variants to a feature flag that is part of a launched experiment. To update variants, reset the experiment to draft.'
                            : undefined
                    }
                    tooltipPlacement="top-start"
                    center
                >
                    Add variant
                </LemonButton>
            )}
        </div>
    )
}
