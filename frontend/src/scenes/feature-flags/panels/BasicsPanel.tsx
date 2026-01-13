import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonDialog, LemonSegmentedButton } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { userLogic } from 'scenes/userLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { tagsModel } from '~/models/tagsModel'
import { AvailableFeature } from '~/types'

import { FeatureFlagEvaluationTags } from '../FeatureFlagEvaluationTags'
import { FeatureFlagVariantsForm, focusVariantKeyField } from '../FeatureFlagVariantsForm'
import { UTM_TAGS } from '../FeatureFlagSnippets'
import { featureFlagLogic } from '../featureFlagLogic'

export function BasicsPanel(): JSX.Element {
    const { featureFlag, multivariateEnabled, variants, nonEmptyVariants, aggregationTargetName, flagType, hasExperiment, isDraftExperiment, variantErrors, experiment } = useValues(featureFlagLogic)
    const { setMultivariateEnabled, setRemoteConfigEnabled, distributeVariantsEqually, addVariant, removeVariant, setFeatureFlag } = useActions(featureFlagLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { tags } = useValues(tagsModel)

    const [hasKeyChanged, setHasKeyChanged] = useState(false)
    const isNewFlag = featureFlag?.id === null

    const filterGroups = featureFlag?.filters?.groups || []

    // Safety check - if featureFlag is not loaded yet, show nothing
    if (!featureFlag) {
        return <div>Loading...</div>
    }

    const confirmRevertMultivariateEnabled = (): void => {
        LemonDialog.open({
            title: 'Change value type?',
            description: 'The existing variants will be lost',
            primaryButton: {
                children: 'Confirm',
                type: 'primary',
                onClick: () => setMultivariateEnabled(false),
                size: 'small',
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            },
        })
    }

    const canEditVariant = (index: number): boolean => {
        if (hasExperiment && !isDraftExperiment) {
            return false
        }
        if (hasExperiment && isDraftExperiment && index === 0) {
            return false
        }
        return true
    }

    return (
        <div className="space-y-4">
            {/* Flag name and key */}
            <LemonField
                name="key"
                label="Flag key"
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
                    ) : (
                        "This is what you'll use in code"
                    )
                }
            >
                {({ value, onChange }) => (
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
                        placeholder="e.g., new-checkout-flow"
                        autoComplete="off"
                        autoCapitalize="off"
                        autoCorrect="off"
                        spellCheck={false}
                    />
                )}
            </LemonField>

            <LemonField name="name" label="Description (optional)">
                <LemonTextArea
                    className="ph-ignore-input"
                    data-attr="feature-flag-description"
                    defaultValue={featureFlag.name || ''}
                    placeholder="What does this flag control? When should it be removed?"
                    rows={2}
                />
            </LemonField>

            {hasAvailableFeature(AvailableFeature.TAGGING) && (
                <LemonField name="tags" label="Tags (optional)">
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

            <LemonDivider />

            {/* Flag type selector */}
            <SceneSection title="Flag type">
                <div data-attr="feature-flag-served-value-segmented-button">
                    <LemonSegmentedButton
                        fullWidth
                        options={[
                            {
                                label: 'Boolean',
                                value: 'boolean',
                                disabledReason: hasExperiment
                                    ? 'This feature flag is associated with an experiment.'
                                    : undefined,
                            },
                            {
                                label: 'Multivariate',
                                value: 'multivariate',
                            },
                        ]}
                        onChange={(value) => {
                            if (value === 'boolean' && nonEmptyVariants.length) {
                                confirmRevertMultivariateEnabled()
                            } else {
                                setMultivariateEnabled(value === 'multivariate')
                                setRemoteConfigEnabled(false)
                                if (value === 'multivariate') {
                                    focusVariantKeyField(0)
                                }
                            }
                        }}
                        value={flagType === 'remote_config' ? 'boolean' : flagType}
                    />
                </div>
                <div className="text-secondary text-sm mt-2">
                    {multivariateEnabled ? (
                        <>
                            {capitalizeFirstLetter(aggregationTargetName)} will be served{' '}
                            <strong>a variant key</strong> according to the below distribution if they match one or more
                            release condition groups.
                        </>
                    ) : (
                        <>
                            {capitalizeFirstLetter(aggregationTargetName)} will be served{' '}
                            <strong>
                                <code>true</code>
                            </strong>{' '}
                            if they match one or more release condition groups.
                        </>
                    )}
                </div>
            </SceneSection>

            {/* Variants (only for multivariate) */}
            {multivariateEnabled && (
                <>
                    <LemonDivider />
                    <SceneSection title="Variants" description="Rollout percentages must add up to 100%">
                        <FeatureFlagVariantsForm
                            variants={variants}
                            payloads={featureFlag.filters?.payloads}
                            filterGroups={filterGroups}
                            onAddVariant={addVariant}
                            onRemoveVariant={removeVariant}
                            onDistributeEqually={distributeVariantsEqually}
                            canEditVariant={canEditVariant}
                            hasExperiment={hasExperiment ?? false}
                            experimentId={experiment?.id}
                            experimentName={experiment?.name}
                            isDraftExperiment={isDraftExperiment}
                            onVariantChange={(index, field, value) => {
                                const currentVariants = [...variants]
                                currentVariants[index] = { ...currentVariants[index], [field]: value }
                                setFeatureFlag({
                                    ...featureFlag,
                                    filters: {
                                        ...featureFlag.filters,
                                        multivariate: {
                                            ...featureFlag.filters.multivariate,
                                            variants: currentVariants,
                                        },
                                    },
                                })
                            }}
                            onPayloadChange={(index, value) => {
                                const currentPayloads = { ...featureFlag.filters.payloads }
                                if (value === undefined) {
                                    delete currentPayloads[index]
                                } else {
                                    currentPayloads[index] = value
                                }
                                setFeatureFlag({
                                    ...featureFlag,
                                    filters: {
                                        ...featureFlag.filters,
                                        payloads: currentPayloads,
                                    },
                                })
                            }}
                            surveys={featureFlag.surveys ?? []}
                            variantErrors={variantErrors}
                        />
                    </SceneSection>
                </>
            )}
        </div>
    )
}
