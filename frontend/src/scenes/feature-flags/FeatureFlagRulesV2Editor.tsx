import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSegmentedButton,
    LemonSelect,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { FeatureFlagLogicProps, slugifyFeatureFlagKey } from './featureFlagLogic'
import { featureFlagRulesV2EditorLogic } from './featureFlagRulesV2EditorLogic'
import { BOOLEAN_OPTIONS, RulesV2RuleEditor } from './RulesV2RuleEditor'

export function FeatureFlagRulesV2Editor({ id }: FeatureFlagLogicProps): JSX.Element {
    const logic = featureFlagRulesV2EditorLogic({ id })
    const { draft, ruleKeys, featureFlag, saving, saveError, saveDisabledReason, fieldError } = useValues(logic)
    const { setDraft, setConfig, addRule, saveRulesV2Flag, editFeatureFlag } = useActions(logic)
    const isNew = id === 'new'

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
                        error={fieldError('key')}
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
                    <LemonField.Pure label="Description" showOptional error={fieldError('name')}>
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
                            error={fieldError('filters.default_value')}
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
