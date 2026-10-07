import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useId } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { tagsModel } from '~/models/tagsModel'

import { FeatureFlagLogicProps, slugifyFeatureFlagKey } from './featureFlagLogic'
import { featureFlagRulesV2EditorLogic } from './featureFlagRulesV2EditorLogic'
import { RulesV2RuleEditor } from './RulesV2RuleEditor'
import { RulesV2ValueInput } from './RulesV2ValueInput'

const RETURN_TYPE_OPTIONS = [
    { value: 'boolean' as const, label: 'Boolean' },
    { value: 'string' as const, label: 'String' },
]

export function FeatureFlagRulesV2Editor({ id }: FeatureFlagLogicProps): JSX.Element {
    const logic = featureFlagRulesV2EditorLogic({ id })
    const { draft, ruleKeys, featureFlag, saving, saveError, saveDisabledReason, fieldError } = useValues(logic)
    const { setDraft, setConfig, setReturnType, addRule, saveRulesV2Flag, editFeatureFlag } = useActions(logic)
    const { tags } = useValues(tagsModel)
    const { loadTagsIfNeeded } = useActions(tagsModel)
    const isNew = id === 'new'
    const keyInputId = useId()
    const descriptionInputId = useId()
    const defaultValueInputId = useId()
    const returnType = draft.config.return_type

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
                        htmlFor={keyInputId}
                        error={fieldError('key')}
                        help={
                            !isNew && draft.key !== featureFlag.key
                                ? 'Changing the key breaks every SDK call that uses the old one.'
                                : undefined
                        }
                    >
                        <LemonInput
                            id={keyInputId}
                            value={draft.key}
                            onChange={(key) => setDraft({ key: slugifyFeatureFlagKey(key) })}
                            data-attr="rules-v2-flag-key"
                            className="ph-ignore-input"
                            autoComplete="off"
                            spellCheck={false}
                            placeholder="e.g. new-checkout"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="Description"
                        htmlFor={descriptionInputId}
                        showOptional
                        error={fieldError('name')}
                    >
                        <LemonTextArea
                            id={descriptionInputId}
                            value={draft.name}
                            onChange={(name) => setDraft({ name })}
                            className="ph-ignore-input"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Tags" showOptional error={fieldError('tags')}>
                        <ObjectTags
                            tags={draft.tags}
                            onChange={(tags) => setDraft({ tags })}
                            onEdit={loadTagsIfNeeded}
                            saving={saving}
                            tagsAvailable={tags.filter((tag: string) => !draft.tags.includes(tag))}
                            data-attr="rules-v2-flag-tags"
                        />
                    </LemonField.Pure>
                    <div className="flex flex-wrap gap-4">
                        <LemonField.Pure label="Return type" error={fieldError('filters.return_type')}>
                            <LemonSelect
                                value={returnType}
                                onChange={setReturnType}
                                options={RETURN_TYPE_OPTIONS}
                                disabledReason={
                                    isNew ? undefined : 'The return type cannot be changed after the flag is created.'
                                }
                                data-attr="rules-v2-return-type"
                            />
                        </LemonField.Pure>
                        <LemonField.Pure
                            label="Default value"
                            htmlFor={defaultValueInputId}
                            help={
                                returnType === 'boolean'
                                    ? "Returned when no rule matches. Null returns no value, so the SDK uses the caller's default."
                                    : "Returned when no rule matches. Leave it empty to return no value, so the SDK uses the caller's default."
                            }
                            error={fieldError('filters.default_value')}
                        >
                            <RulesV2ValueInput
                                id={defaultValueInputId}
                                returnType={returnType}
                                value={draft.config.default_value}
                                onChange={(default_value) => setConfig({ default_value })}
                                nullable
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
                            returnType={returnType}
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
