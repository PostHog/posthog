import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { FeatureFlagRulesV2DraftRule } from '~/types'

import { FeatureFlagLogicProps } from './featureFlagLogic'
import { BOOLEAN_OPTIONS, featureFlagRulesV2EditorLogic, withRuleType } from './featureFlagRulesV2EditorLogic'
import { PercentageInput } from './PercentageInput'

export function RulesV2RuleEditor({
    id,
    index,
    rule,
    ruleCount,
    ruleKey,
}: FeatureFlagLogicProps & {
    index: number
    rule: FeatureFlagRulesV2DraftRule
    ruleCount: number
    ruleKey: number
}): JSX.Element {
    const { fieldError } = useValues(featureFlagRulesV2EditorLogic({ id }))
    const { updateRule, removeRule, moveRule } = useActions(featureFlagRulesV2EditorLogic({ id }))
    const path = `filters.rules[${index}]`
    const descriptionInputId = useId()
    const rolloutInputId = useId()

    return (
        <div className="rounded border p-3 bg-surface-primary flex flex-col gap-3" data-attr="rules-v2-rule">
            <div className="flex items-center gap-2">
                <span className="font-semibold">Rule {index + 1}</span>
                <LemonSelect
                    size="small"
                    value={rule.rule_type}
                    onChange={(ruleType) => updateRule(index, withRuleType(rule, ruleType))}
                    options={[
                        { value: 'targeted_release', label: 'Targeted release' },
                        { value: 'percentage_rollout', label: 'Percentage rollout' },
                    ]}
                    data-attr="rules-v2-rule-type"
                />
                <div className="flex-1" />
                <LemonButton
                    icon={<IconArrowUp />}
                    size="small"
                    tooltip="Move up"
                    data-attr="rules-v2-move-rule-up"
                    disabledReason={index === 0 ? 'This rule is evaluated first.' : undefined}
                    onClick={() => moveRule(index, index - 1)}
                />
                <LemonButton
                    icon={<IconArrowDown />}
                    size="small"
                    tooltip="Move down"
                    data-attr="rules-v2-move-rule-down"
                    disabledReason={index === ruleCount - 1 ? 'This rule is evaluated last.' : undefined}
                    onClick={() => moveRule(index, index + 1)}
                />
                <LemonButton
                    icon={<IconTrash />}
                    size="small"
                    status="danger"
                    tooltip="Remove rule"
                    data-attr="rules-v2-remove-rule"
                    onClick={() => removeRule(index)}
                />
            </div>
            {fieldError(path) && <LemonBanner type="error">{fieldError(path)}</LemonBanner>}
            <LemonField.Pure
                label="Description"
                htmlFor={descriptionInputId}
                showOptional
                error={fieldError(`${path}.description`)}
            >
                <LemonInput
                    id={descriptionInputId}
                    value={rule.description ?? ''}
                    onChange={(description) => updateRule(index, { ...rule, description: description || undefined })}
                />
            </LemonField.Pure>
            <LemonField.Pure
                label="Match persons where"
                help={rule.targeting.properties.length === 0 ? 'No conditions: every person matches.' : undefined}
                error={fieldError(`${path}.targeting`)}
            >
                <PropertyFilters
                    pageKey={`rules-v2-${id}-${ruleKey}`}
                    propertyFilters={rule.targeting.properties}
                    onChange={(properties) => updateRule(index, { ...rule, targeting: { properties } })}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
                    hasRowOperator={false}
                    logicalRowDivider
                    sendAllKeyUpdates
                    addText="Add condition"
                />
            </LemonField.Pure>
            {rule.rule_type === 'percentage_rollout' && (
                <div className="flex flex-wrap gap-4">
                    <LemonField.Pure
                        label="Rollout percentage"
                        htmlFor={rolloutInputId}
                        className="w-40"
                        error={fieldError(`${path}.rollout_percentage`)}
                    >
                        <PercentageInput
                            id={rolloutInputId}
                            value={rule.rollout_percentage}
                            onChange={(rollout_percentage) => updateRule(index, { ...rule, rollout_percentage })}
                            data-attr="rules-v2-rollout-percentage"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Persons outside the rollout" error={fieldError(`${path}.on_rollout_miss`)}>
                        <LemonSelect
                            value={rule.on_rollout_miss}
                            onChange={(on_rollout_miss) => updateRule(index, { ...rule, on_rollout_miss })}
                            options={[
                                { value: 'continue', label: 'Continue to the next rule' },
                                { value: 'return_default', label: 'Get the default value' },
                            ]}
                            data-attr="rules-v2-rollout-miss"
                        />
                    </LemonField.Pure>
                </div>
            )}
            <LemonField.Pure label="Value" error={fieldError(`${path}.value`)}>
                <LemonSegmentedButton
                    size="small"
                    value={String(rule.value)}
                    onChange={(value) => updateRule(index, { ...rule, value: value === 'true' })}
                    options={BOOLEAN_OPTIONS}
                    data-attr="rules-v2-rule-value"
                />
            </LemonField.Pure>
        </div>
    )
}
