import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { memo, useRef } from 'react'

import { IconCopy, IconEllipsis, IconPause, IconPlay, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonMenu, LemonSelect } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconArrowDown, IconArrowUp, SortableDragIcon } from 'lib/lemon-ui/icons'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { Noun } from '~/models/groupsModel'
import { FeatureFlagRulesV2DraftRule, FeatureFlagRulesV2ReturnType, JsonType } from '~/types'

import { formatPercentage } from 'products/feature_flags/frontend/FractionalRolloutWarning'
import {
    RULES_V2_RULE_TYPES,
    RULES_V2_RULE_TYPE_META,
    RulesV2FieldError,
    RulesV2MatchCountText,
    RulesV2PausedRow,
    RulesV2PausedTag,
    RulesV2RuleNumber,
    RulesV2RuleRow,
    RulesV2ShadowedWarning,
    rulesV2ReachedPercentage,
    rulesV2RolloutMissText,
    rulesV2RuleTypeMenuLabel,
    useRulesV2MatchCount,
} from 'products/feature_flags/frontend/RulesV2Flow'

import { FeatureFlagLogicProps } from './featureFlagLogic'
import { withRuleType } from './featureFlagRulesV2Draft'
import { featureFlagRulesV2EditorLogic } from './featureFlagRulesV2EditorLogic'
import { PercentageInput } from './PercentageInput'
import { RulesV2HoldoutRow, RulesV2VariantsRow } from './RulesV2ExperimentFields'
import { RulesV2ValueInput } from './RulesV2ValueInput'

const RULE_TYPE_OPTIONS = RULES_V2_RULE_TYPES.map((ruleType) => ({
    value: ruleType,
    label: RULES_V2_RULE_TYPE_META[ruleType].label,
    icon: RULES_V2_RULE_TYPE_META[ruleType].icon,
    labelInMenu: rulesV2RuleTypeMenuLabel(ruleType),
}))

const ROLLOUT_MISS_OPTIONS = [
    { value: 'continue' as const, description: 'Later rules, or the default value, decide.' },
    { value: 'return_default' as const, description: 'Later rules never see them.' },
].map(({ value, description }) => ({
    value,
    label: rulesV2RolloutMissText(value),
    labelInMenu: (
        <div className="flex flex-col py-0.5">
            <span>{capitalizeFirstLetter(rulesV2RolloutMissText(value))}</span>
            <span className="text-xs text-secondary">{description}</span>
        </div>
    ),
}))

function RolloutRow({
    id,
    index,
    rule,
    subjects,
    count,
}: FeatureFlagLogicProps & {
    index: number
    rule: Extract<FeatureFlagRulesV2DraftRule, { rollout_percentage: number }>
    subjects: Noun
    count: ReturnType<typeof useRulesV2MatchCount>
}): JSX.Element {
    const { fieldError } = useValues(featureFlagRulesV2EditorLogic({ id }))
    const { updateRule } = useActions(featureFlagRulesV2EditorLogic({ id }))
    const path = `filters.rules[${index}]`
    const heldOut = rule.rule_type === 'experiment' ? (rule.holdout?.exclusion_percentage ?? 0) : 0
    const reached = rulesV2ReachedPercentage(rule)
    const error = fieldError(`${path}.rollout_percentage`) ?? fieldError(`${path}.on_rollout_miss`)

    return (
        <RulesV2RuleRow
            label="Rollout"
            aside={
                reached === null ? null : (
                    <RulesV2MatchCountText count={count} subjects={subjects} rolloutPercentage={reached} />
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
            {rule.rollout_percentage < 100 && (
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-secondary">The other {formatPercentage(100 - rule.rollout_percentage)}</span>
                    <LemonSelect
                        size="small"
                        value={rule.on_rollout_miss}
                        onChange={(on_rollout_miss) => updateRule(index, { ...rule, on_rollout_miss })}
                        options={ROLLOUT_MISS_OPTIONS}
                        data-attr="rules-v2-rollout-miss"
                    />
                </div>
            )}
            <RulesV2FieldError error={error} />
        </RulesV2RuleRow>
    )
}

export const RulesV2RuleEditor = memo(function RulesV2RuleEditor({
    id,
    index,
    rule,
    ruleCount,
    ruleKey,
    returnType,
    defaultValue,
    subjects,
    groupTypeIndex,
    shadowedBy,
    onRemoved,
}: FeatureFlagLogicProps & {
    index: number
    rule: FeatureFlagRulesV2DraftRule
    ruleCount: number
    ruleKey: number
    returnType: FeatureFlagRulesV2ReturnType
    defaultValue: JsonType | null
    subjects: Noun
    groupTypeIndex: number | null
    shadowedBy: number | null
    onRemoved: () => void
}): JSX.Element {
    const { fieldError } = useValues(featureFlagRulesV2EditorLogic({ id }))
    const { updateRule, removeRule, moveRule, duplicateRule } = useActions(featureFlagRulesV2EditorLogic({ id }))
    const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
        id: ruleKey,
    })
    const path = `filters.rules[${index}]`
    const seedError = fieldError(`${path}.seed`)
    const properties = rule.targeting.properties
    const count = useRulesV2MatchCount(properties, groupTypeIndex)
    const paused = rule.rule_type === 'experiment' && rule.paused
    const ruleError = fieldError(path)
    const menuButtonRef = useRef<HTMLButtonElement | null>(null)
    // The menu closes without restoring focus, and a move re-inserts the card, so focus goes back to its menu button.
    const refocusMenu = (): void => {
        setTimeout(() => menuButtonRef.current?.focus())
    }

    return (
        <div
            ref={setNodeRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ transform: CSS.Translate.toString(transform), transition }}
            className={clsx(
                'rounded border bg-surface-primary relative',
                isDragging && 'z-10 shadow-lg ring-1 ring-accent',
                (ruleError || seedError) && 'border-danger'
            )}
            role="group"
            aria-label={`Rule ${index + 1}`}
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
                {paused && <RulesV2PausedTag />}
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
                            onClick: () => {
                                removeRule(index)
                                onRemoved()
                            },
                            'data-attr': 'rules-v2-remove-rule',
                        },
                    ]}
                >
                    <LemonButton
                        ref={menuButtonRef}
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
                <RulesV2ShadowedWarning shadowedBy={shadowedBy} subjects={subjects} />
                <RulesV2RuleRow label="If" aside={<RulesV2MatchCountText count={count} subjects={subjects} />}>
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
                    <RulesV2PausedRow
                        subjects={subjects}
                        defaultValue={defaultValue}
                        until="you resume"
                        className="text-warning-dark"
                    />
                )}
                {rule.rule_type === 'experiment' && (
                    <RulesV2HoldoutRow id={id} index={index} rule={rule} subjects={subjects} />
                )}
                {rule.rule_type !== 'targeted_release' && (
                    <RolloutRow id={id} index={index} rule={rule} subjects={subjects} count={count} />
                )}
                {rule.rule_type === 'experiment' ? (
                    <RulesV2VariantsRow id={id} index={index} rule={rule} returnType={returnType} />
                ) : (
                    <RulesV2RuleRow label="Serve">
                        <div className="flex flex-col gap-1 max-w-80">
                            <RulesV2ValueInput
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
})
