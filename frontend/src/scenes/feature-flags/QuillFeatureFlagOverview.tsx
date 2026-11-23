import { useActions, useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import { Button, Switch, Text } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import ViewRecordingsPlaylistButton from 'lib/components/ViewRecordingButton/ViewRecordingsPlaylistButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { SceneDescriptionRow } from '~/layout/scenes/components/SceneDescriptionRow'
import { SceneSettingsCard } from '~/layout/scenes/components/SceneSettingsCard'
import { SceneSettingsRow } from '~/layout/scenes/components/SceneSettingsRow'
import { SceneTagsRow } from '~/layout/scenes/components/SceneTagsRow'
import { AccessControlLevel, AccessControlResourceType, FeatureFlagEvaluationRuntime, FeatureFlagType } from '~/types'

import { deletedCohortDisabledReason } from 'products/feature_flags/frontend/deletedCohortFilters'
import {
    UNSUPPORTED_CONFIG_DISABLED_REASON,
    featureFlagConfigFormat,
    isRulesV2FeatureFlagConfig,
    isV1FeatureFlagConfig,
} from 'products/feature_flags/frontend/featureFlagConfigFormat'
import { FeatureFlagConfigReadonlyNotice } from 'products/feature_flags/frontend/FeatureFlagConfigReadonlyNotice'
import { FeatureFlagImplementationPanel } from 'products/feature_flags/frontend/FeatureFlagImplementationPanel'
import { FeatureFlagRulesV2Readonly } from 'products/feature_flags/frontend/FeatureFlagRulesV2Readonly'

import { FeatureFlagEvaluationContexts } from './FeatureFlagEvaluationContexts'
import { featureFlagLogic } from './featureFlagLogic'
import { FeatureFlagReleaseConditionsReadonly } from './FeatureFlagReleaseConditionsReadonly'
import { FeatureFlagVariantsSection } from './FeatureFlagVariantsSection'
import { RecentFeatureFlagInsights } from './RecentFeatureFlagInsightsCard'

const VIEW_ONLY_REASON = "You only have view access to this feature flag. To make changes, contact the flag's creator."
const DELETED_REASON = 'Restore this feature flag to change it.'

const EVALUATION_RUNTIME_LABELS: Record<FeatureFlagEvaluationRuntime, string> = {
    [FeatureFlagEvaluationRuntime.CLIENT]: 'Client-side only',
    [FeatureFlagEvaluationRuntime.SERVER]: 'Server-side only',
    [FeatureFlagEvaluationRuntime.ALL]: 'Both client and server',
}

export function QuillFeatureFlagOverview({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const { recordingFilterForFlag, featureFlagActiveUpdateLoading, deletedCohortFilters } = useValues(featureFlagLogic)
    const { toggleFeatureFlagActive, editFeatureFlag, saveDescriptionInline, saveTagsInline, saveSidebarTags } =
        useActions(featureFlagLogic)

    // The flag predates the rename of tags to evaluation contexts, so its name still says tags.
    const hasEvaluationContexts = !!featureFlags[FEATURE_FLAGS.FLAG_EVALUATION_TAGS]
    const v1Filters = isV1FeatureFlagConfig(featureFlag.filters) ? featureFlag.filters : null
    const variants = v1Filters?.multivariate?.variants ?? []
    const payload = v1Filters?.payloads?.['true']
    const managedByExperiment = (featureFlag.experiment_set?.length ?? 0) > 0
    const editDisabledReason = featureFlag.deleted ? DELETED_REASON : !featureFlag.can_edit ? VIEW_ONLY_REASON : null

    const flagType = featureFlag.is_remote_configuration
        ? 'Remote config'
        : v1Filters?.multivariate
          ? 'Multivariate'
          : 'Boolean'

    const editButton = (dataAttr: string, disabledReason?: string): JSX.Element | null =>
        featureFlag.deleted || !v1Filters ? null : (
            <AccessControlAction
                resourceType={AccessControlResourceType.FeatureFlag}
                minAccessLevel={AccessControlLevel.Editor}
                userAccessLevel={featureFlag.user_access_level}
            >
                {({ disabledReason: accessDisabledReason }) => (
                    <Button
                        variant="outline"
                        disabledReason={disabledReason ?? accessDisabledReason}
                        onClick={() => editFeatureFlag(true, { expandAdvanced: true })}
                        data-attr={dataAttr}
                    >
                        Edit
                    </Button>
                )}
            </AccessControlAction>
        )

    return (
        <div className="flex max-w-240 flex-col gap-4">
            <SceneSettingsCard title="General" dataAttr="feature-flag-settings-general">
                <SceneSettingsRow label="Key" description="What your code checks. Change it from Edit.">
                    <Text size="xs" className="m-0 min-w-0 truncate font-mono" render={<span translate="no" />}>
                        {featureFlag.key}
                    </Text>
                    <Button
                        size="icon-sm"
                        aria-label="Copy key"
                        tooltip="Copy key"
                        onClick={() => void copyToClipboard(featureFlag.key, 'feature flag key')}
                        data-attr="feature-flag-settings-copy-key"
                    >
                        <IconCopy />
                    </Button>
                </SceneSettingsRow>
                <SceneDescriptionRow
                    value={featureFlag.name}
                    onSave={editDisabledReason ? undefined : saveDescriptionInline}
                    disabledReason={editDisabledReason}
                    dataAttr="feature-flag-settings-description"
                />
                {hasEvaluationContexts ? (
                    <SceneSettingsRow label="Tags and evaluation contexts">
                        <FeatureFlagEvaluationContexts
                            tags={featureFlag.tags}
                            evaluationContexts={featureFlag.evaluation_contexts || []}
                            onSave={saveSidebarTags}
                            evaluationContextsDisabledReason={
                                v1Filters ? null : "Evaluation contexts can't be changed on this flag yet."
                            }
                            flagId={featureFlag.id}
                            context={editDisabledReason ? 'static' : 'sidebar'}
                        />
                    </SceneSettingsRow>
                ) : (
                    <SceneTagsRow
                        tags={featureFlag.tags}
                        onSave={saveTagsInline}
                        disabledReason={editDisabledReason}
                        dataAttr="feature-flag-settings-tags"
                    />
                )}
            </SceneSettingsCard>

            <SceneSettingsCard title="Status">
                <SceneSettingsRow
                    label="Enabled"
                    description="When off, every user gets false, whatever the release conditions say."
                >
                    <AccessControlAction
                        resourceType={AccessControlResourceType.FeatureFlag}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={featureFlag.user_access_level}
                    >
                        {({ disabledReason }) => (
                            <Switch
                                aria-label="Enabled"
                                checked={featureFlag.active}
                                onCheckedChange={toggleFeatureFlagActive}
                                disabled={featureFlagActiveUpdateLoading}
                                disabledReason={
                                    disabledReason ??
                                    editDisabledReason ??
                                    (featureFlagConfigFormat(featureFlag.filters) === 'unsupported'
                                        ? UNSUPPORTED_CONFIG_DISABLED_REASON
                                        : !featureFlag.active
                                          ? deletedCohortDisabledReason(deletedCohortFilters)
                                          : null)
                                }
                                data-attr="feature-flag-settings-enabled"
                            />
                        )}
                    </AccessControlAction>
                </SceneSettingsRow>
            </SceneSettingsCard>

            <SceneSettingsCard
                title="Evaluation"
                action={editButton(
                    'feature-flag-settings-edit-evaluation',
                    managedByExperiment ? 'Variants are managed by the linked experiment' : undefined
                )}
            >
                <SceneSettingsRow label="Type">
                    <Text size="xs" className="m-0">
                        {flagType}
                    </Text>
                </SceneSettingsRow>
                <SceneSettingsRow label="Runs on">
                    <Text size="xs" className="m-0">
                        {EVALUATION_RUNTIME_LABELS[featureFlag.evaluation_runtime] ??
                            EVALUATION_RUNTIME_LABELS[FeatureFlagEvaluationRuntime.ALL]}
                    </Text>
                </SceneSettingsRow>
                {!featureFlag.is_remote_configuration && (
                    <SceneSettingsRow
                        label="Persist across sign-in"
                        description="Keeps a user's value when they go from anonymous to identified."
                    >
                        <Text size="xs" className="m-0">
                            {featureFlag.ensure_experience_continuity ? 'On' : 'Off'}
                        </Text>
                    </SceneSettingsRow>
                )}
                {v1Filters && !v1Filters.multivariate && (
                    <SceneSettingsRow label="Payload">
                        {payload ? (
                            <Text size="xs" className="m-0 min-w-0 truncate font-mono" render={<code translate="no" />}>
                                {typeof payload === 'string' ? payload : JSON.stringify(payload)}
                            </Text>
                        ) : (
                            <Text size="xs" variant="muted" className="m-0">
                                None
                            </Text>
                        )}
                    </SceneSettingsRow>
                )}
            </SceneSettingsCard>

            {/* Variants and release conditions are richer than a row of settings, so they keep their own views
                until they get a settings-shaped design. */}
            {v1Filters?.multivariate && variants.length > 0 && (
                <FeatureFlagVariantsSection featureFlag={featureFlag} variants={variants} />
            )}
            {v1Filters && !featureFlag.is_remote_configuration && (
                <FeatureFlagReleaseConditionsReadonly
                    id={String(featureFlag.id)}
                    filters={v1Filters}
                    isDisabled={!featureFlag.active}
                    evaluationRuntime={featureFlag.evaluation_runtime}
                />
            )}
            {!v1Filters &&
                (isRulesV2FeatureFlagConfig(featureFlag.filters) ? (
                    <FeatureFlagRulesV2Readonly
                        config={featureFlag.filters}
                        active={featureFlag.active}
                        editButton={
                            featureFlag.deleted ? null : (
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.FeatureFlag}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={featureFlag.user_access_level}
                                >
                                    {({ disabledReason }) => (
                                        <Button
                                            variant="outline"
                                            disabledReason={disabledReason}
                                            onClick={() => editFeatureFlag(true)}
                                            data-attr="edit-rules-v2-rules"
                                        >
                                            Edit rules
                                        </Button>
                                    )}
                                </AccessControlAction>
                            )
                        }
                    />
                ) : (
                    <FeatureFlagConfigReadonlyNotice filters={featureFlag.filters} />
                ))}

            {!featureFlag.is_remote_configuration && (
                <SceneSettingsCard
                    title="Related insights"
                    action={
                        <ViewRecordingsPlaylistButton
                            filters={recordingFilterForFlag}
                            type="secondary"
                            size="xsmall"
                            data-attr="feature-flag-view-recordings"
                        />
                    }
                >
                    <div className="px-4 py-3">
                        <RecentFeatureFlagInsights />
                    </div>
                </SceneSettingsCard>
            )}

            <FeatureFlagImplementationPanel featureFlag={featureFlag} />
        </div>
    )
}
