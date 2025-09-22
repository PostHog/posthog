import 'kea'
import { Group } from 'kea-forms'

import { IconBalance, IconPlus, IconRewindPlay, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { alphabet } from 'lib/utils'
import { JSONEditorInput } from 'scenes/feature-flags/JSONEditorInput'

import { FeatureFlagGroupType, MultivariateFlagVariant } from '~/types'

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
}: FeatureFlagVariantsFormProps): JSX.Element {
    const variantRolloutSum = variants.reduce((sum, variant) => sum + (variant.rollout_percentage || 0), 0)
    const areVariantRolloutsValid = variantRolloutSum === 100

    function variantConcatWithPunctuation(phrases: string[]): string {
        if (phrases === null || phrases.length < 3) {
            return phrases.join(' and ')
        }
        return `${phrases[0]} and ${phrases.length - 1} more sets`
    }

    function focusVariantKeyField(index: number): void {
        setTimeout(
            () => document.querySelector<HTMLElement>(`.VariantFormList input[data-key-index="${index}"]`)?.focus(),
            50
        )
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
                <Group key={index} name="filters">
                    <div className="VariantFormList__row grid gap-2">
                        <div className="flex items-center justify-center">
                            <Lettermark name={alphabet[index]} color={LettermarkColor.Gray} />
                        </div>
                        <div className="col-span-4">
                            <LemonField name={['multivariate', 'variants', index, 'key']}>
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
                                />
                            </LemonField>
                        </div>
                        <div className="col-span-6">
                            <LemonField name={['multivariate', 'variants', index, 'name']}>
                                <LemonInput
                                    data-attr="feature-flag-variant-name"
                                    className="ph-ignore-input"
                                    placeholder="Description"
                                />
                            </LemonField>
                        </div>
                        <div className="col-span-8">
                            <LemonField name={['payloads', index]}>
                                {({ value, onChange }) => {
                                    return (
                                        <JSONEditorInput
                                            onChange={(newValue) => {
                                                onChange(newValue === '' ? undefined : newValue)
                                            }}
                                            value={value}
                                            placeholder='{"key": "value"}'
                                        />
                                    )
                                }}
                            </LemonField>
                        </div>
                        <div className="col-span-3">
                            <LemonField name={['multivariate', 'variants', index, 'rollout_percentage']}>
                                {({ value, onChange }) => (
                                    <div>
                                        <LemonInput
                                            type="number"
                                            min={0}
                                            max={100}
                                            value={value.toString()}
                                            onChange={(changedValue) => {
                                                const valueInt =
                                                    changedValue !== undefined && !isNaN(changedValue)
                                                        ? parseInt(changedValue.toString())
                                                        : 0

                                                onChange(valueInt)
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
                                                                (group) =>
                                                                    group.variant != null &&
                                                                    group.variant === variant.key
                                                            )
                                                            .map(
                                                                (variant) =>
                                                                    'Set ' +
                                                                    (filterGroups.findIndex(
                                                                        (group) => group === variant
                                                                    ) +
                                                                        1)
                                                            )
                                                    )}
                                                </strong>
                                            </span>
                                        )}
                                    </div>
                                )}
                            </LemonField>
                        </div>
                        <div className="flex items-center justify-center">
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
                </Group>
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
