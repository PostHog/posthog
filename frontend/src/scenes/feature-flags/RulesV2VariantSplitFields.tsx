import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconBalance, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { FeatureFlagRulesV2DraftExperimentRule, FeatureFlagRulesV2ReturnType, FeatureFlagRulesV2Variant } from '~/types'

import { FeatureFlagLogicProps } from './featureFlagLogic'
import {
    MAX_VARIANTS,
    MIN_VARIANTS,
    moved,
    newVariant,
    withEqualWeights,
    withVariantKey,
} from './featureFlagRulesV2Draft'
import { featureFlagRulesV2EditorLogic } from './featureFlagRulesV2EditorLogic'
import { PercentageInput } from './PercentageInput'
import { RulesV2ValueInput } from './RulesV2ValueInput'

const NEW_HOLDOUT = { id: null, exclusion_percentage: 10 }

interface VariantSplitFieldsProps extends FeatureFlagLogicProps {
    index: number
    rule: FeatureFlagRulesV2DraftExperimentRule
}

/** Pause and holdout, which a variant split checks before its rollout. Seeds are server-owned and never shown. */
export function RulesV2VariantSplitGuards({ id, index, rule }: VariantSplitFieldsProps): JSX.Element {
    const { fieldError } = useValues(featureFlagRulesV2EditorLogic({ id }))
    const { updateRule } = useActions(featureFlagRulesV2EditorLogic({ id }))
    const path = `filters.rules[${index}]`
    const holdoutInputId = useId()
    const { holdout, ...withoutHoldout } = rule
    const holdoutSeedError = fieldError(`${path}.holdout.seed`)

    return (
        <div className="flex flex-wrap gap-4">
            <LemonField.Pure
                help="Matching persons get the default value while the split is paused."
                error={fieldError(`${path}.paused`)}
            >
                <LemonSwitch
                    label="Paused"
                    checked={rule.paused}
                    onChange={(paused) => updateRule(index, { ...rule, paused })}
                    bordered
                    data-attr="rules-v2-split-paused"
                />
            </LemonField.Pure>
            <div className="flex flex-col gap-2">
                <LemonField.Pure
                    help="Held-out persons get the default value and no variant."
                    error={fieldError(`${path}.holdout`) ?? (holdoutSeedError && `Holdout seed: ${holdoutSeedError}`)}
                >
                    <LemonSwitch
                        label="Hold out persons"
                        checked={!!holdout}
                        // Removing the holdout drops its stored seed; the server keeps it if the holdout is added back before saving.
                        onChange={(on) => updateRule(index, on ? { ...rule, holdout: NEW_HOLDOUT } : withoutHoldout)}
                        bordered
                        data-attr="rules-v2-split-holdout"
                    />
                </LemonField.Pure>
                {holdout && (
                    <LemonField.Pure
                        label="Held out"
                        htmlFor={holdoutInputId}
                        className="w-40"
                        error={fieldError(`${path}.holdout.exclusion_percentage`)}
                    >
                        <PercentageInput
                            id={holdoutInputId}
                            value={holdout.exclusion_percentage}
                            onChange={(exclusion_percentage) =>
                                updateRule(index, { ...rule, holdout: { ...holdout, exclusion_percentage } })
                            }
                            data-attr="rules-v2-split-holdout-percentage"
                        />
                    </LemonField.Pure>
                )}
            </div>
        </div>
    )
}

export function RulesV2VariantsField({
    id,
    index,
    rule,
    returnType,
}: VariantSplitFieldsProps & { returnType: FeatureFlagRulesV2ReturnType }): JSX.Element {
    const { fieldError } = useValues(featureFlagRulesV2EditorLogic({ id }))
    const { updateRule } = useActions(featureFlagRulesV2EditorLogic({ id }))
    const path = `filters.rules[${index}]`
    const { variants } = rule
    const setVariants = (next: FeatureFlagRulesV2Variant[]): void => updateRule(index, { ...rule, variants: next })
    const setVariant = (variantIndex: number, variant: FeatureFlagRulesV2Variant): void =>
        setVariants(variants.map((current, i) => (i === variantIndex ? variant : current)))
    // Shown under the rows rather than as the field's error, which would outline every input in the table.
    const variantsError = fieldError(`${path}.variants`)

    return (
        <LemonField.Pure
            label="Variants"
            help="Each enrolled person gets one variant, picked by weight. Changing the weights or their order moves some persons to another variant."
        >
            <div className="flex flex-col gap-2" data-attr="rules-v2-variants">
                <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_7rem_6.5rem] gap-2 items-center text-xs font-semibold text-secondary">
                    <span>Key</span>
                    <span>Value</span>
                    <span className="flex items-center gap-1">
                        Weight
                        <LemonButton
                            size="xsmall"
                            icon={<IconBalance />}
                            tooltip="Distribute weights equally"
                            onClick={() => setVariants(withEqualWeights(variants))}
                            data-attr="rules-v2-distribute-weights"
                        />
                    </span>
                    <span />
                </div>
                {variants.map((variant, variantIndex) => {
                    const variantPath = `${path}.variants[${variantIndex}]`
                    const label = `Variant ${variantIndex + 1}`
                    return (
                        <div
                            // Rows hold no state of their own, so index keys are safe.
                            key={variantIndex}
                            className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_7rem_6.5rem] gap-2 items-start"
                            data-attr="rules-v2-variant"
                        >
                            <LemonField.Pure error={fieldError(`${variantPath}.key`) ?? fieldError(variantPath)}>
                                <LemonInput
                                    aria-label={`${label} key`}
                                    value={variant.key}
                                    onChange={(key) =>
                                        setVariant(variantIndex, withVariantKey(variant, key, returnType))
                                    }
                                    placeholder="e.g. test"
                                    className="ph-ignore-input"
                                    autoComplete="off"
                                    spellCheck={false}
                                    data-attr="rules-v2-variant-key"
                                />
                            </LemonField.Pure>
                            <LemonField.Pure error={fieldError(`${variantPath}.value`)}>
                                <RulesV2ValueInput
                                    returnType={returnType}
                                    aria-label={`${label} value`}
                                    value={variant.value}
                                    onChange={(value) => setVariant(variantIndex, { ...variant, value })}
                                    data-attr="rules-v2-variant-value"
                                />
                            </LemonField.Pure>
                            <LemonField.Pure error={fieldError(`${variantPath}.weight`)}>
                                <PercentageInput
                                    aria-label={`${label} weight`}
                                    value={variant.weight}
                                    onChange={(weight) => setVariant(variantIndex, { ...variant, weight })}
                                    data-attr="rules-v2-variant-weight"
                                />
                            </LemonField.Pure>
                            <div className="flex">
                                <LemonButton
                                    icon={<IconArrowUp />}
                                    size="small"
                                    tooltip="Move up"
                                    disabledReason={variantIndex === 0 ? 'This variant is first.' : undefined}
                                    onClick={() => setVariants(moved(variants, variantIndex, variantIndex - 1))}
                                    data-attr="rules-v2-move-variant-up"
                                />
                                <LemonButton
                                    icon={<IconArrowDown />}
                                    size="small"
                                    tooltip="Move down"
                                    disabledReason={
                                        variantIndex === variants.length - 1 ? 'This variant is last.' : undefined
                                    }
                                    onClick={() => setVariants(moved(variants, variantIndex, variantIndex + 1))}
                                    data-attr="rules-v2-move-variant-down"
                                />
                                <LemonButton
                                    icon={<IconTrash />}
                                    size="small"
                                    status="danger"
                                    tooltip="Remove variant"
                                    disabledReason={
                                        variants.length <= MIN_VARIANTS
                                            ? `A split needs at least ${MIN_VARIANTS} variants.`
                                            : undefined
                                    }
                                    onClick={() => setVariants(variants.filter((_, i) => i !== variantIndex))}
                                    data-attr="rules-v2-remove-variant"
                                />
                            </div>
                        </div>
                    )
                })}
                {variantsError && <LemonField.Error error={variantsError} />}
                <div>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlusSmall />}
                        disabledReason={
                            variants.length >= MAX_VARIANTS
                                ? `A split has at most ${MAX_VARIANTS} variants.`
                                : undefined
                        }
                        onClick={() => setVariants([...variants, newVariant(returnType, variants.length)])}
                        data-attr="rules-v2-add-variant"
                    >
                        Add variant
                    </LemonButton>
                </div>
            </div>
        </LemonField.Pure>
    )
}
