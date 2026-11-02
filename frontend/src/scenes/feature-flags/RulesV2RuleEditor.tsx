import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useId, useRef } from 'react'

import { IconCopy, IconEllipsis, IconPause, IconPlay, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonMenu, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconArrowDown, IconArrowUp, SortableDragIcon } from 'lib/lemon-ui/icons'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'

import { FeatureFlagRulesV2DraftRule, FeatureFlagRulesV2ReturnType, JsonType } from '~/types'

import {
    RULES_V2_RULE_TYPES,
    RULES_V2_RULE_TYPE_META,
    RulesV2MatchCountText,
    RulesV2FieldError,
    RulesV2RuleNumber,
    RulesV2RuleRow,
    RulesV2ShadowedWarning,
    RulesV2Value,
    useRulesV2MatchCount,
} from 'products/feature_flags/frontend/RulesV2Flow'

import { FeatureFlagLogicProps } from './featureFlagLogic'
import { withRuleType } from './featureFlagRulesV2Draft'
import { featureFlagRulesV2EditorLogic } from './featureFlagRulesV2EditorLogic'
import { PercentageInput } from './PercentageInput'
import { RulesV2HoldoutRow, RulesV2VariantsRow } from './RulesV2ExperimentFields'
import { RulesV2ValueInput } from './RulesV2ValueInput'

export interface RulesV2Subjects {
    singular: string
    plural: string
}

const RULE_TYPE_OPTIONS = RULES_V2_RULE_TYPES.map((ruleType) => {
    const meta = RULES_V2_RULE_TYPE_META[ruleType]
    return {
        value: ruleType,
        label: meta.label,
        icon: meta.icon,
        labelInMenu: (
            <div className="flex flex-col py-0.5">
                <span className="font-semibold">{meta.label}</span>
                <span className="text-xs text-secondary font-normal">{meta.description}</span>
            </div>
        ),
    }
})

function RolloutRow({
    id,
    index,
    rule,
    subjects,
    count,
}: FeatureFlagLogicProps & {
    index: number
    rule: Extract<FeatureFlagRulesV2DraftRule, { rollout_percentage: number }>
    subjects: RulesV2Subjects
    count: ReturnType<typeof useRulesV2MatchCount>
}): JSX.Element {
    const { fieldError } = useValues(featureFlagRulesV2EditorLogic({ id }))
    const { updateRule } = useActions(featureFlagRulesV2EditorLogic({ id }))
    const rolloutInputId = useId()
    const path = `filters.rules[${index}]`
    const heldOut = rule.rule_type === 'experiment' ? (rule.holdout?.exclusion_percentage ?? 0) : 0
    const rest = Math.round((100 - rule.rollout_percentage) * 100) / 100
    const error = fieldError(`${path}.rollout_percentage`) ?? fieldError(`${path}.on_rollout_miss`)

    return (
        <RulesV2RuleRow
            label="Rollout"
            aside={
                // A paused experiment enrolls no one, so it has no reach to estimate.
                rule.rule_type === 'experiment' && rule.paused ? null : (
                    <RulesV2MatchCountText
                        count={count}
                        properties={rule.targeting.properties}
                        subjects={subjects}
                        rolloutPercentage={(rule.rollout_percentage * (100 - heldOut)) / 100}
                    />
                )
            }
        >
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 min-h-7">
                <LemonSlider
                    className="w-40 m-0"
                    min={0}
                    max={100}
                    step={1}
                    value={rule.rollout_percentage}
                    onChange={(rollout_percentage) => updateRule(index, { ...rule, rollout_percentage })}
                />
                <div className="w-24">
                    <PercentageInput
                        id={rolloutInputId}
                        aria-label="Rollout percentage"
                        value={rule.rollout_percentage}
                        onChange={(rollout_percentage) => updateRule(index, { ...rule, rollout_percentage })}
                        data-attr="rules-v2-rollout-percentage"
                    />
                </div>
                <span className="text-secondary">
                    of matching {subjects.plural}
                    {heldOut > 0 ? ' not held out' : ''}
                    {rule.rule_type === 'experiment' ? ' are enrolled' : ''}
                </span>
            </div>
            {rest > 0 && (
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-secondary">The other {rest}%</span>
                    <LemonSelect
                        size="small"
                        value={rule.on_rollout_miss}
                        onChange={(on_rollout_miss) => updateRule(index, { ...rule, on_rollout_miss })}
                        options={[
                            {
                                value: 'continue',
                                label: 'continue to the next rule',
                                labelInMenu: (
                                    <div className="flex flex-col py-0.5">
                                        <span>Continue to the next rule</span>
                                        <span className="text-xs text-secondary">
                                            Later rules, or the default value, decide.
                                        </span>
                                    </div>
                                ),
                            },
                            {
                                value: 'return_default',
                                label: 'get the default value',
                                labelInMenu: (
                                    <div className="flex flex-col py-0.5">
                                        <span>Get the default value</span>
                                        <span className="text-xs text-secondary">Later rules never see them.</span>
                                    </div>
                                ),
                            },
                        ]}
                        data-attr="rules-v2-rollout-miss"
                    />
                </div>
            )}
            <RulesV2FieldError error={error} />
        </RulesV2RuleRow>
    )
}

export function RulesV2RuleEditor({
    id,
    index,
    rule,
    ruleCount,
    ruleKey,
    returnType,
    defaultValue,
    subjects,
    shadowedBy,
}: FeatureFlagLogicProps & {
    index: number
    rule: FeatureFlagRulesV2DraftRule
    ruleCount: number
    ruleKey: number
    returnType: FeatureFlagRulesV2ReturnType
    defaultValue: JsonType | null
    subjects: RulesV2Subjects
    shadowedBy: number | null
}): JSX.Element {
    const { fieldError } = useValues(featureFlagRulesV2EditorLogic({ id }))
    const { updateRule, removeRule, moveRule, duplicateRule } = useActions(featureFlagRulesV2EditorLogic({ id }))
    const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
        id: ruleKey,
    })
    const path = `filters.rules[${index}]`
    const valueInputId = useId()
    const seedError = fieldError(`${path}.seed`)
    const properties = rule.targeting.properties
    const count = useRulesV2MatchCount(properties)
    const paused = rule.rule_type === 'experiment' && rule.paused
    const ruleError = fieldError(path)
    const cardRef = useRef<HTMLDivElement | null>(null)
    // The menu closes without restoring focus, and a move re-inserts the card, so focus goes back to its menu button.
    const refocusMenu = (): void => {
        setTimeout(() => cardRef.current?.querySelector<HTMLElement>('[data-attr="rules-v2-rule-menu"]')?.focus())
    }

    return (
        <div
            ref={(element) => {
                setNodeRef(element)
                cardRef.current = element
            }}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ transform: CSS.Translate.toString(transform), transition }}
            className={clsx(
                'rounded border bg-surface-primary relative',
                isDragging && 'z-10 shadow-lg ring-1 ring-accent',
                (ruleError || seedError) && 'border-danger'
            )}
            data-attr="rules-v2-rule"
        >
            <div className="flex items-center gap-1.5 pl-1 pr-2 py-1.5 border-b">
                <button
                    type="button"
                    ref={setActivatorNodeRef}
                    className="cursor-grab active:cursor-grabbing text-muted hover:text-default border-none bg-transparent p-1 rounded hover:bg-fill-button-tertiary-hover flex"
                    aria-label={`Reorder rule ${index + 1}`}
                    {...attributes}
                    {...listeners}
                    data-attr="rules-v2-rule-drag-handle"
                >
                    <SortableDragIcon />
                </button>
                <RulesV2RuleNumber index={index} muted={shadowedBy !== null} />
                <LemonSelect
                    size="small"
                    value={rule.rule_type}
                    onChange={(ruleType) => updateRule(index, withRuleType(rule, ruleType, returnType))}
                    options={RULE_TYPE_OPTIONS}
                    dropdownMatchSelectWidth={false}
                    data-attr="rules-v2-rule-type"
                />
                <LemonInput
                    size="small"
                    className="flex-1 min-w-24 border-transparent bg-transparent hover:border-primary focus-within:border-primary"
                    aria-label={`Rule ${index + 1} description`}
                    placeholder="Add a description"
                    value={rule.description ?? ''}
                    onChange={(description) => updateRule(index, { ...rule, description: description || undefined })}
                    data-attr="rules-v2-rule-description"
                />
                {paused && (
                    <LemonTag type="warning" icon={<IconPause />}>
                        Paused
                    </LemonTag>
                )}
                {rule.rule_type === 'experiment' && (
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={rule.paused ? <IconPlay /> : <IconPause />}
                        tooltip={
                            rule.paused
                                ? 'Matching users get variants again.'
                                : 'Matching users get the default value until you resume. Nobody is enrolled meanwhile.'
                        }
                        onClick={() => updateRule(index, { ...rule, paused: !rule.paused })}
                        data-attr="rules-v2-experiment-paused"
                    >
                        {rule.paused ? 'Resume' : 'Pause'}
                    </LemonButton>
                )}
                <LemonMenu
                    items={[
                        {
                            label: 'Move up',
                            icon: <IconArrowUp />,
                            disabledReason: index === 0 ? 'This rule is checked first.' : undefined,
                            onClick: () => {
                                moveRule(index, index - 1)
                                refocusMenu()
                            },
                            'data-attr': 'rules-v2-move-rule-up',
                        },
                        {
                            label: 'Move down',
                            icon: <IconArrowDown />,
                            disabledReason: index === ruleCount - 1 ? 'This rule is checked last.' : undefined,
                            onClick: () => {
                                moveRule(index, index + 1)
                                refocusMenu()
                            },
                            'data-attr': 'rules-v2-move-rule-down',
                        },
                        {
                            label: 'Duplicate',
                            icon: <IconCopy />,
                            onClick: () => {
                                duplicateRule(index)
                                refocusMenu()
                            },
                            'data-attr': 'rules-v2-duplicate-rule',
                        },
                        {
                            label: 'Delete rule',
                            icon: <IconTrash />,
                            status: 'danger',
                            onClick: () => removeRule(index),
                            'data-attr': 'rules-v2-remove-rule',
                        },
                    ]}
                >
                    <LemonButton
                        size="small"
                        icon={<IconEllipsis />}
                        aria-label={`Rule ${index + 1} actions`}
                        data-attr="rules-v2-rule-menu"
                    />
                </LemonMenu>
            </div>
            <div className="px-3 py-2.5 flex flex-col gap-2">
                {ruleError && (
                    <LemonBanner type="error" className="text-sm">
                        {ruleError}
                    </LemonBanner>
                )}
                {seedError && (
                    <LemonBanner type="error" className="text-sm">
                        Assignment seed: {seedError}
                    </LemonBanner>
                )}
                <RulesV2ShadowedWarning shadowedBy={shadowedBy} subjects={subjects.singular} />
                <RulesV2RuleRow
                    label="If"
                    aside={<RulesV2MatchCountText count={count} properties={properties} subjects={subjects} />}
                >
                    <div className="flex flex-wrap items-center gap-2">
                        {properties.length === 0 && <span className="leading-7">All {subjects.plural}</span>}
                        <PropertyFilters
                            pageKey={`rules-v2-${id}-${ruleKey}`}
                            propertyFilters={properties}
                            onChange={(next) => updateRule(index, { ...rule, targeting: { properties: next } })}
                            taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
                            hasRowOperator={false}
                            logicalRowDivider
                            sendAllKeyUpdates
                            buttonText="Add condition"
                            buttonSize="small"
                        />
                    </div>
                    <RulesV2FieldError error={fieldError(`${path}.targeting`)} />
                </RulesV2RuleRow>
                {paused && (
                    <RulesV2RuleRow label="Paused" className="text-warning-dark">
                        <span className="leading-7">
                            Matching {subjects.plural} get the default value <RulesV2Value value={defaultValue} /> until
                            you resume. Nobody is enrolled meanwhile.
                        </span>
                    </RulesV2RuleRow>
                )}
                {rule.rule_type === 'experiment' && (
                    <RulesV2HoldoutRow id={id} index={index} rule={rule} subjects={subjects.plural} />
                )}
                {rule.rule_type !== 'targeted_release' && (
                    <RolloutRow id={id} index={index} rule={rule} subjects={subjects} count={count} />
                )}
                {rule.rule_type === 'experiment' ? (
                    <RulesV2VariantsRow
                        id={id}
                        index={index}
                        rule={rule}
                        returnType={returnType}
                        subjects={subjects.plural}
                    />
                ) : (
                    <RulesV2RuleRow label="Serve">
                        <div className="flex flex-col gap-1 max-w-80">
                            <RulesV2ValueInput
                                id={valueInputId}
                                aria-label="Value"
                                returnType={returnType}
                                value={rule.value}
                                onChange={(value) => updateRule(index, { ...rule, value })}
                                data-attr="rules-v2-rule-value"
                            />
                            <RulesV2FieldError error={fieldError(`${path}.value`)} />
                        </div>
                    </RulesV2RuleRow>
                )}
            </div>
        </div>
    )
}
