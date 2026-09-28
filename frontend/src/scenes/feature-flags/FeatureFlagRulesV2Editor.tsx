import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSegmentedButton,
    LemonSelect,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { FeatureFlagRulesV2DraftRule } from '~/types'

import { FeatureFlagLogicProps, slugifyFeatureFlagKey } from './featureFlagLogic'
import { featureFlagRulesV2EditorLogic, withRuleType } from './featureFlagRulesV2EditorLogic'
import { PercentageInput } from './PercentageInput'

const BOOLEAN_OPTIONS = [
    { value: 'true', label: 'true' },
    { value: 'false', label: 'false' },
]

function RulesV2RuleEditor({
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
    const { saveError } = useValues(featureFlagRulesV2EditorLogic({ id }))
    const { updateRule, removeRule, moveRule } = useActions(featureFlagRulesV2EditorLogic({ id }))
    const path = `filters.rules[${index}]`
    const errorFor = (field: string): string | undefined => (saveError?.field === field ? saveError.message : undefined)

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
                    disabledReason={index === 0 ? 'This rule is evaluated first.' : undefined}
                    onClick={() => moveRule(index, index - 1)}
                />
                <LemonButton
                    icon={<IconArrowDown />}
                    size="small"
                    tooltip="Move down"
                    disabledReason={index === ruleCount - 1 ? 'This rule is evaluated last.' : undefined}
                    onClick={() => moveRule(index, index + 1)}
                />
                <LemonButton
                    icon={<IconTrash />}
                    size="small"
                    status="danger"
                    tooltip="Remove rule"
                    onClick={() => removeRule(index)}
                />
            </div>
            {errorFor(path) && <LemonBanner type="error">{errorFor(path)}</LemonBanner>}
            <LemonField.Pure label="Description" showOptional error={errorFor(`${path}.description`)}>
                <LemonInput
                    value={rule.description ?? ''}
                    onChange={(description) => updateRule(index, { ...rule, description: description || undefined })}
                />
            </LemonField.Pure>
            <LemonField.Pure
                label="Match persons where"
                help={rule.targeting.properties.length === 0 ? 'No conditions: every person matches.' : undefined}
                error={errorFor(`${path}.targeting`)}
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
                        className="w-40"
                        error={errorFor(`${path}.rollout_percentage`)}
                    >
                        <PercentageInput
                            value={rule.rollout_percentage}
                            onChange={(rollout_percentage) => updateRule(index, { ...rule, rollout_percentage })}
                            data-attr="rules-v2-rollout-percentage"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Persons outside the rollout" error={errorFor(`${path}.on_rollout_miss`)}>
                        <LemonSelect
                            value={rule.on_rollout_miss}
                            onChange={(on_rollout_miss) => updateRule(index, { ...rule, on_rollout_miss })}
                            options={[
                                { value: 'continue', label: 'Continue to the next rule' },
                                { value: 'return_default', label: 'Get the default value' },
                            ]}
                        />
                    </LemonField.Pure>
                </div>
            )}
            <LemonField.Pure label="Value" error={errorFor(`${path}.value`)}>
                <LemonSegmentedButton
                    size="small"
                    value={String(rule.value)}
                    onChange={(value) => updateRule(index, { ...rule, value: value === 'true' })}
                    options={BOOLEAN_OPTIONS}
                />
            </LemonField.Pure>
        </div>
    )
}

export function FeatureFlagRulesV2Editor({ id }: FeatureFlagLogicProps): JSX.Element {
    const logic = featureFlagRulesV2EditorLogic({ id })
    const { draft, ruleKeys, featureFlag, saving, saveError, saveDisabledReason } = useValues(logic)
    const { setDraft, setConfig, addRule, saveRulesV2Flag, editFeatureFlag } = useActions(logic)
    const isNew = id === 'new'
    const errorFor = (field: string): string | undefined => (saveError?.field === field ? saveError.message : undefined)

    return (
        <div className="flex flex-col gap-4" data-attr="feature-flag-rules-v2-editor">
            <SceneTitleSection
                name={draft.key || 'New rules v2 flag'}
                resourceType={{ type: !isNew && featureFlag.active ? 'feature_flag' : 'feature_flag_off' }}
                actions={
                    <>
                        <LemonButton
                            type="secondary"
                            size="small"
                            data-attr="cancel-rules-v2-flag"
                            onClick={() => (isNew ? router.actions.push(urls.featureFlags()) : editFeatureFlag(false))}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            data-attr="save-rules-v2-flag"
                            loading={saving}
                            disabledReason={saveDisabledReason}
                            onClick={saveRulesV2Flag}
                        >
                            Save
                        </LemonButton>
                    </>
                }
            />
            <SceneContent>
                {saveError && saveError.field === null && (
                    <LemonBanner type="error" data-attr="rules-v2-save-error">
                        {saveError.message}
                    </LemonBanner>
                )}
                <div className="rounded border p-3 bg-surface-primary flex flex-col gap-3 max-w-200">
                    <LemonField.Pure
                        label="Flag key"
                        error={errorFor('key')}
                        help={
                            !isNew && draft.key !== featureFlag.key
                                ? 'Changing the key breaks every SDK call that uses the old one.'
                                : undefined
                        }
                    >
                        <LemonInput
                            value={draft.key}
                            onChange={(key) => setDraft({ key: slugifyFeatureFlagKey(key) })}
                            data-attr="rules-v2-flag-key"
                            className="ph-ignore-input"
                            autoComplete="off"
                            spellCheck={false}
                            placeholder="e.g. new-checkout"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Description" showOptional error={errorFor('name')}>
                        <LemonTextArea
                            value={draft.name}
                            onChange={(name) => setDraft({ name })}
                            className="ph-ignore-input"
                        />
                    </LemonField.Pure>
                    <div className="flex flex-wrap gap-4">
                        <LemonField.Pure label="Return type">
                            <LemonSelect
                                value={draft.config.return_type}
                                options={[{ value: 'boolean', label: 'Boolean' }]}
                                disabledReason="Other return types are not available yet."
                            />
                        </LemonField.Pure>
                        <LemonField.Pure
                            label="Default value"
                            help="Returned when no rule matches. Null returns no value, so the SDK uses the caller's default."
                            error={errorFor('filters.default_value')}
                        >
                            <LemonSegmentedButton
                                size="small"
                                value={String(draft.config.default_value)}
                                onChange={(value) =>
                                    setConfig({ default_value: value === 'null' ? null : value === 'true' })
                                }
                                options={[...BOOLEAN_OPTIONS, { value: 'null', label: 'null' }]}
                                data-attr="rules-v2-default-value"
                            />
                        </LemonField.Pure>
                    </div>
                    {isNew && (
                        <p className="text-xs text-muted m-0">
                            New flags are created disabled. Enable the flag from its page after saving.
                        </p>
                    )}
                </div>
                <div className="flex flex-col gap-2 max-w-200">
                    <span className="font-semibold">Rules</span>
                    <p className="text-xs text-muted m-0">
                        Rules are evaluated top to bottom; the first match decides.
                    </p>
                    {draft.config.rules.map((rule, index) => (
                        <RulesV2RuleEditor
                            key={ruleKeys[index]}
                            ruleKey={ruleKeys[index]}
                            id={id}
                            index={index}
                            rule={rule}
                            ruleCount={draft.config.rules.length}
                        />
                    ))}
                    <div>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPlusSmall />}
                            onClick={addRule}
                            data-attr="rules-v2-add-rule"
                        >
                            Add rule
                        </LemonButton>
                    </div>
                </div>
            </SceneContent>
        </div>
    )
}
