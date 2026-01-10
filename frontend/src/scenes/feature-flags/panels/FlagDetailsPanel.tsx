import { useValues } from 'kea'
import { useState } from 'react'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { tagsModel } from '~/models/tagsModel'
import { AvailableFeature } from '~/types'

import { FeatureFlagEvaluationTags } from '../FeatureFlagEvaluationTags'
import { UTM_TAGS } from '../FeatureFlagSnippets'
import { featureFlagLogic } from '../featureFlagLogic'

export function FlagDetailsPanel(): JSX.Element {
    const { featureFlag } = useValues(featureFlagLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { tags } = useValues(tagsModel)

    // Track if the key for an existing flag is being changed
    const [hasKeyChanged, setHasKeyChanged] = useState(false)
    const isNewFlag = featureFlag.id === null

    return (
        <div className="space-y-4">
            <LemonField
                name="key"
                label="Key"
                help={
                    hasKeyChanged && !isNewFlag ? (
                        <span className="text-warning">
                            <b>Warning! </b>Changing this key will
                            <Link
                                to={`https://posthog.com/docs/feature-flags${UTM_TAGS}#feature-flag-persistence`}
                                target="_blank"
                                targetBlankIcon
                            >
                                {' '}
                                affect the persistence of your flag
                            </Link>
                        </span>
                    ) : undefined
                }
            >
                {({ value, onChange }) => (
                    <>
                        <LemonInput
                            value={value}
                            onChange={(v) => {
                                if (v !== value) {
                                    setHasKeyChanged(true)
                                }
                                onChange(v)
                            }}
                            data-attr="feature-flag-key"
                            className="ph-ignore-input"
                            autoFocus
                            placeholder="examples: new-landing-page, betaFeature, ab_test_1"
                            autoComplete="off"
                            autoCapitalize="off"
                            autoCorrect="off"
                            spellCheck={false}
                        />
                        <span className="text-secondary text-sm">Feature flag keys must be unique</span>
                    </>
                )}
            </LemonField>

            <LemonField name="name" label="Description">
                <LemonTextArea
                    className="ph-ignore-input"
                    data-attr="feature-flag-description"
                    defaultValue={featureFlag.name || ''}
                />
            </LemonField>

            {hasAvailableFeature(AvailableFeature.TAGGING) && (
                <LemonField name="tags" label="Tags">
                    {({ value: formTags, onChange: onChangeTags }) => (
                        <>
                            {featureFlags[FEATURE_FLAGS.FLAG_EVALUATION_TAGS] ? (
                                <LemonField name="evaluation_tags">
                                    {({ value: formEvalTags, onChange: onChangeEvalTags }) => (
                                        <FeatureFlagEvaluationTags
                                            tags={formTags}
                                            evaluationTags={formEvalTags || []}
                                            onChange={(updatedTags, updatedEvaluationTags) => {
                                                onChangeTags(updatedTags)
                                                onChangeEvalTags(updatedEvaluationTags)
                                            }}
                                            tagsAvailable={tags.filter((tag: string) => !formTags?.includes(tag))}
                                            className="mt-2"
                                            flagId={featureFlag.id}
                                            context="form"
                                        />
                                    )}
                                </LemonField>
                            ) : (
                                <ObjectTags
                                    tags={formTags}
                                    onChange={onChangeTags}
                                    saving={false}
                                    tagsAvailable={tags.filter((tag: string) => !formTags?.includes(tag))}
                                    className="mt-2"
                                />
                            )}
                        </>
                    )}
                </LemonField>
            )}
        </div>
    )
}
