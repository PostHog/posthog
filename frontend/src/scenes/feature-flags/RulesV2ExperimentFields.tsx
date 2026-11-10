import { useActions, useValues } from 'kea'

import { IconBalance, IconCheckCircle, IconPlusSmall, IconTrash, IconWarning } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { Noun } from '~/models/groupsModel'
import { FeatureFlagRulesV2DraftExperimentRule, FeatureFlagRulesV2ReturnType, FeatureFlagRulesV2Variant } from '~/types'

import {
    RulesV2AllocationBar,
    RulesV2FieldError,
    RulesV2RuleRow,
    rulesV2ExperimentSegments,
    rulesV2VariantColor,
} from 'products/feature_flags/frontend/RulesV2Flow'

import { FeatureFlagLogicProps } from './featureFlagLogic'
import {
    MAX_VARIANTS,
    MIN_VARIANTS,
    NEW_HOLDOUT,
    moved,
    newVariant,
    rulesV2VariantWeightTotal,
    withEqualWeights,
    withVariantKey,
} from './featureFlagRulesV2Draft'
import { featureFlagRulesV2EditorLogic } from './featureFlagRulesV2EditorLogic'
import { PercentageInput } from './PercentageInput'
import { RulesV2ValueInput } from './RulesV2ValueInput'

interface ExperimentFieldsProps extends FeatureFlagLogicProps {
    index: number
    rule: FeatureFlagRulesV2DraftExperimentRule
}

/** The holdout, which an experiment rule checks before its rollout. Seeds are server-owned and never shown. */
export function RulesV2HoldoutRow({
    id,
    index,
    rule,
    subjects,
}: ExperimentFieldsProps & { subjects: Noun }): JSX.Element {
    const { fieldError } = useValues(featureFlagRulesV2EditorLogic({ id }))
    const { updateRule } = useActions(featureFlagRulesV2EditorLogic({ id }))
    const path = `filters.rules[${index}]`
    const { holdout, ...withoutHoldout } = rule
    const holdoutSeedError = fieldError(`${path}.holdout.seed`)
    const error =
        fieldError(`${path}.holdout`) ??
        fieldError(`${path}.holdout.exclusion_percentage`) ??
        (holdoutSeedError && `Holdout seed: ${holdoutSeedError}`)

    return (
        <RulesV2RuleRow label="Holdout">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 min-h-7">
                <LemonSwitch
                    aria-label="Hold out users"
                    checked={!!holdout}
                    // Removing the holdout drops its stored seed; the server keeps it if the holdout is added back before saving.
                    onChange={(on) => updateRule(index, on ? { ...rule, holdout: NEW_HOLDOUT } : withoutHoldout)}
                    data-attr="rules-v2-experiment-holdout"
                />
                {holdout ? (
                    <>
                        <span>Hold out</span>
                        <div className="w-24">
                            <PercentageInput
                                aria-label="Holdout excludes"
                                value={holdout.exclusion_percentage}
                                onChange={(exclusion_percentage) =>
                                    updateRule(index, { ...rule, holdout: { ...holdout, exclusion_percentage } })
                                }
                                data-attr="rules-v2-experiment-holdout-percentage"
                            />
                        </div>
                        <span className="text-secondary">
                            of matching {subjects.plural}. They get the default value and no variant.
                        </span>
                    </>
                ) : (
                    <span className="text-secondary">
                        No holdout. Turn it on to keep a share of {subjects.plural} out of every variant.
                    </span>
                )}
            </div>
            <RulesV2FieldError error={error} />
        </RulesV2RuleRow>
    )
}

function WeightTotal({ variants }: { variants: FeatureFlagRulesV2Variant[] }): JSX.Element {
    const total = rulesV2VariantWeightTotal(variants)
    const ok = total === 100
    return (
        <span
            className={`inline-flex items-center gap-1 text-xs tabular-nums ${ok ? 'text-success' : 'text-danger'}`}
            data-attr="rules-v2-weight-total"
        >
            {ok ? <IconCheckCircle /> : <IconWarning />}
            Total {total}%
        </span>
    )
}

const VARIANT_GRID = 'grid grid-cols-[0.625rem_minmax(0,1fr)_minmax(0,1fr)_6rem_auto] gap-x-2 items-start'

export function RulesV2VariantsRow({
    id,
    index,
    rule,
    returnType,
}: ExperimentFieldsProps & { returnType: FeatureFlagRulesV2ReturnType }): JSX.Element {
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
        <RulesV2RuleRow label="Variants">
            <div className="flex flex-col gap-2 pt-1" data-attr="rules-v2-variants">
                <div className="flex items-center gap-3">
                    <RulesV2AllocationBar segments={rulesV2ExperimentSegments(rule)} className="flex-1" />
                    <WeightTotal variants={variants} />
                </div>
                <div className={`${VARIANT_GRID} text-xxs font-semibold uppercase tracking-wide text-muted`}>
                    <span />
                    <span>Key</span>
                    <span>Serves</span>
                    <span>Share</span>
                    <span className="w-[5.25rem]" />
                </div>
                {variants.map((variant, variantIndex) => {
                    const variantPath = `${path}.variants[${variantIndex}]`
                    const label = `Variant ${variantIndex + 1}`
                    return (
                        <div
                            // Rows hold no state of their own; with index keys, focus stays put when a row moves.
                            key={variantIndex}
                            className={VARIANT_GRID}
                            data-attr="rules-v2-variant"
                        >
                            <span
                                className="size-2.5 rounded-full mt-2.5"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ background: rulesV2VariantColor(variantIndex) }}
                            />
                            <LemonField.Pure error={fieldError(`${variantPath}.key`) ?? fieldError(variantPath)}>
                                <LemonInput
                                    aria-label={`${label} key`}
                                    value={variant.key}
                                    onChange={(key) =>
                                        setVariant(variantIndex, withVariantKey(variant, key, returnType))
                                    }
                                    placeholder="e.g. test"
                                    size="small"
                                    className="ph-ignore-input font-mono"
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
                                    tooltip="Remove variant"
                                    disabledReason={
                                        variants.length <= MIN_VARIANTS
                                            ? `An experiment needs at least ${MIN_VARIANTS} variants.`
                                            : undefined
                                    }
                                    onClick={() => setVariants(variants.filter((_, i) => i !== variantIndex))}
                                    data-attr="rules-v2-remove-variant"
                                />
                            </div>
                        </div>
                    )
                })}
                <RulesV2FieldError error={variantsError} />
                <div className="flex flex-wrap items-center gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlusSmall />}
                        disabledReason={
                            variants.length >= MAX_VARIANTS
                                ? `An experiment has at most ${MAX_VARIANTS} variants.`
                                : undefined
                        }
                        onClick={() => setVariants([...variants, newVariant(returnType, variants.length)])}
                        data-attr="rules-v2-add-variant"
                    >
                        Add variant
                    </LemonButton>
                    <LemonButton
                        type="tertiary"
                        size="small"
                        icon={<IconBalance />}
                        onClick={() => setVariants(withEqualWeights(variants))}
                        data-attr="rules-v2-distribute-weights"
                    >
                        Split equally
                    </LemonButton>
                    <span className="text-xs text-secondary">
                        Changing weights or their order moves some enrolled users to another variant.
                    </span>
                </div>
            </div>
        </RulesV2RuleRow>
    )
}
