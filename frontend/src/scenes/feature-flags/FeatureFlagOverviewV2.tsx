import './FeatureFlag.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconCode, IconFlag, IconGlobe, IconLaptop, IconList, IconMessage, IconServer } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonDialog, LemonDivider, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import ViewRecordingsPlaylistButton from 'lib/components/ViewRecordingButton/ViewRecordingsPlaylistButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, FeatureFlagEvaluationRuntime, FeatureFlagType } from '~/types'

import { EditableOverviewSection } from './EditableOverviewSection'
import { FeatureFlagEvaluationContexts } from './FeatureFlagEvaluationContexts'
import { FeatureFlagInstructions } from './FeatureFlagInstructions'
import { featureFlagLogic } from './featureFlagLogic'
import {
    FeatureFlagReleaseConditionsReadonly,
    FeatureFlagSuperConditionsReadonly,
} from './FeatureFlagReleaseConditionsReadonly'
import { FeatureFlagVariantsSection } from './FeatureFlagVariantsSection'
import { JSONEditorInput } from './JSONEditorInput'
import { RecentFeatureFlagInsights } from './RecentFeatureFlagInsightsCard'

interface FeatureFlagOverviewV2Props {
    featureFlag: FeatureFlagType
    onGetFeedback?: (variantKey?: string) => void
}

interface TagsDisplayProps {
    tags: string[]
    evaluationContexts: string[]
    flagId: number | null
    hasEvaluationContexts: boolean
}

function TagsDisplay({ tags, evaluationContexts, flagId, hasEvaluationContexts }: TagsDisplayProps): JSX.Element {
    const hasTags = tags.length > 0 || evaluationContexts.length > 0

    if (hasEvaluationContexts && hasTags) {
        return (
            <FeatureFlagEvaluationContexts
                tags={tags}
                evaluationContexts={evaluationContexts}
                flagId={flagId}
                context="static"
            />
        )
    }

    if (tags.length > 0) {
        return <ObjectTags tags={tags} staticOnly />
    }

    return <span className="text-muted">No tags</span>
}

/**
 * V2 readonly overview for feature flags, gated behind FEATURE_FLAGS_V2.
 *
 * NOTE: This component is currently rendered conditionally in FeatureFlag.tsx
 * based on the useFormUI flag. If other entry points need to render this overview,
 * ensure the gate is checked there as well.
 */
export function FeatureFlagOverviewV2({ featureFlag, onGetFeedback }: FeatureFlagOverviewV2Props): JSX.Element {
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const { recordingFilterForFlag, featureFlagActiveUpdateLoading } = useValues(featureFlagLogic)
    const { toggleFeatureFlagActive } = useActions(featureFlagLogic)
    const { addProductIntentForCrossSell } = useActions(teamLogic)

    const hasEvaluationTags = !!featureFlags[FEATURE_FLAGS.FLAG_EVALUATION_TAGS]
    const hasEvaluationRuntimes = !!featureFlags[FEATURE_FLAGS.FLAG_EVALUATION_RUNTIMES]

    const multivariateEnabled = !!featureFlag.filters?.multivariate
    const variants = featureFlag.filters?.multivariate?.variants || []
    const hasPayload = !!featureFlag.filters?.payloads?.['true']

    const reportViewRecordingsClicked = (): void => {
        posthog.capture('viewed recordings from feature flag', {
            multivariate: multivariateEnabled.toString(),
        })
    }

    const handleToggleClick = (): void => {
        LemonDialog.open({
            title: featureFlag.active ? 'Disable feature flag?' : 'Enable feature flag?',
            description: featureFlag.active
                ? 'This will immediately disable the flag for all users. Are you sure?'
                : 'This will immediately enable the flag according to its release conditions. Are you sure?',
            primaryButton: {
                children: featureFlag.active ? 'Disable' : 'Enable',
                status: featureFlag.active ? 'danger' : 'default',
                onClick: () => toggleFeatureFlagActive(!featureFlag.active),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    const getFlagTypeDisplay = (): { icon: JSX.Element; label: string; description: string } => {
        if (featureFlag.is_remote_configuration) {
            return {
                icon: <IconCode className="text-lg" />,
                label: 'Remote config',
                description: 'Single payload without feature flag logic',
            }
        }
        if (multivariateEnabled) {
            return {
                icon: <IconList className="text-lg" />,
                label: 'Multivariate',
                description: 'Multiple variants with rollout percentages (A/B/n test)',
            }
        }
        return {
            icon: <IconFlag className="text-lg" />,
            label: 'Boolean',
            description: 'Release toggle (boolean) with optional static payload',
        }
    }

    const flagTypeDisplay = getFlagTypeDisplay()

    const getEvaluationRuntimeDisplay = (): { icon: JSX.Element; label: string; tag: string } => {
        switch (featureFlag.evaluation_runtime) {
            case FeatureFlagEvaluationRuntime.CLIENT:
                return {
                    icon: <IconLaptop className="text-lg text-muted" />,
                    label: 'Client-side only',
                    tag: 'Single-user apps',
                }
            case FeatureFlagEvaluationRuntime.SERVER:
                return {
                    icon: <IconServer className="text-lg text-muted" />,
                    label: 'Server-side only',
                    tag: 'Multi-user systems',
                }
            default:
                return {
                    icon: <IconGlobe className="text-lg text-muted" />,
                    label: 'Both client and server',
                    tag: 'Single + multi-user',
                }
        }
    }

    const evaluationRuntimeDisplay = getEvaluationRuntimeDisplay()

    const flagTypeCard = (
        <div className="flex flex-col gap-2">
            <label className="text-sm font-semibold">Flag type</label>
            <div className="flex items-center gap-3 p-3 rounded border bg-surface-secondary">
                {flagTypeDisplay.icon}
                <div className="flex flex-col">
                    <span className="font-medium">{flagTypeDisplay.label}</span>
                    <span className="text-xs text-muted">{flagTypeDisplay.description}</span>
                </div>
            </div>
        </div>
    )

    return (
        <div className="flex flex-col gap-6">
            <div className="flex gap-4 flex-wrap items-start">
                <div className="flex-1 min-w-64 flex flex-col gap-4">
                    <div className="rounded border p-4 bg-bg-light flex flex-col gap-3">
                        {featureFlag.deleted ? (
                            <div className="flex items-center justify-between">
                                <span className="text-sm font-medium">Status</span>
                                <LemonTag type="danger" size="small">
                                    Deleted
                                </LemonTag>
                            </div>
                        ) : (
                            <AccessControlAction
                                resourceType={AccessControlResourceType.FeatureFlag}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={featureFlag.user_access_level}
                            >
                                <LemonSwitch
                                    checked={featureFlag.active}
                                    onChange={handleToggleClick}
                                    loading={featureFlagActiveUpdateLoading}
                                    disabledReason={
                                        !featureFlag.can_edit
                                            ? "You only have view access to this feature flag. To make changes, contact the flag's creator."
                                            : null
                                    }
                                    label="Enable feature flag"
                                    bordered
                                    fullWidth
                                />
                            </AccessControlAction>
                        )}
                    </div>

                    <EditableOverviewSection editOptions={{ expandAdvanced: true }}>
                        <div className="flex flex-col gap-4">
                            <div className="font-semibold">Advanced options</div>

                            <div className="flex flex-col gap-2">
                                {!hasEvaluationTags && <label className="text-sm font-medium">Tags</label>}
                                <TagsDisplay
                                    tags={featureFlag.tags || []}
                                    evaluationContexts={featureFlag.evaluation_contexts || []}
                                    flagId={featureFlag.id}
                                    hasEvaluationContexts={hasEvaluationTags}
                                />
                            </div>

                            {hasEvaluationRuntimes && (
                                <>
                                    <LemonDivider className="my-1" />

                                    <div className="flex flex-col gap-2">
                                        <label className="text-sm font-medium">Evaluation runtime</label>
                                        <div className="flex items-center gap-2">
                                            {evaluationRuntimeDisplay.icon}
                                            <span className="font-medium text-sm">
                                                {evaluationRuntimeDisplay.label}
                                            </span>
                                            <LemonTag type="muted" size="small">
                                                {evaluationRuntimeDisplay.tag}
                                            </LemonTag>
                                        </div>
                                    </div>
                                </>
                            )}

                            {!featureFlag.is_remote_configuration && (
                                <>
                                    <LemonDivider className="my-1" />

                                    <div className="flex flex-col gap-2">
                                        <label className="text-sm font-medium">Persistence</label>
                                        <span className="text-sm text-muted">
                                            {featureFlag.ensure_experience_continuity ? (
                                                <>
                                                    This flag <b className="text-default">persists</b> across
                                                    authentication steps
                                                </>
                                            ) : (
                                                <>
                                                    This flag <b className="text-default">does not persist</b> across
                                                    authentication steps
                                                </>
                                            )}
                                        </span>
                                    </div>
                                </>
                            )}
                        </div>
                    </EditableOverviewSection>

                    {!featureFlag.is_remote_configuration && (
                        <div className="rounded border p-4 bg-bg-light flex flex-col gap-3">
                            <div className="font-semibold">Insights</div>
                            <RecentFeatureFlagInsights />

                            <div className="flex flex-col gap-3 mt-2 pt-3 border-t border-border-light">
                                <div className="flex items-start gap-2">
                                    <span className="text-sm text-muted flex-1">
                                        Watch recordings of users exposed to this flag
                                    </span>
                                    <ViewRecordingsPlaylistButton
                                        className="shrink-0"
                                        filters={recordingFilterForFlag}
                                        type="secondary"
                                        size="small"
                                        data-attr="feature-flag-view-recordings"
                                        onClick={() => {
                                            reportViewRecordingsClicked()
                                            addProductIntentForCrossSell({
                                                from: ProductKey.FEATURE_FLAGS,
                                                to: ProductKey.SESSION_REPLAY,
                                                intent_context: ProductIntentContext.FEATURE_FLAG_VIEW_RECORDINGS,
                                            })
                                        }}
                                    />
                                </div>
                                {onGetFeedback && (
                                    <div className="flex items-start gap-2">
                                        <span className="text-sm text-muted flex-1">
                                            Get feedback from users who see this flag
                                        </span>
                                        <LemonButton
                                            className="shrink-0"
                                            onClick={() => onGetFeedback()}
                                            type="secondary"
                                            size="small"
                                            sideIcon={<IconMessage />}
                                        >
                                            Get feedback
                                        </LemonButton>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </div>

                <div className="flex-[2] min-w-80 flex flex-col gap-4">
                    {multivariateEnabled && variants.length > 0 ? (
                        <EditableOverviewSection
                            disabledReason={
                                featureFlag.experiment_set && featureFlag.experiment_set.length > 0
                                    ? 'Variants are managed by the linked experiment'
                                    : undefined
                            }
                        >
                            <div className="flex flex-col gap-4">
                                {flagTypeCard}
                                <FeatureFlagVariantsSection featureFlag={featureFlag} variants={variants} />
                            </div>
                        </EditableOverviewSection>
                    ) : (
                        <EditableOverviewSection>
                            <div className="flex flex-col gap-4">
                                {flagTypeCard}
                                <div className="flex flex-col gap-2">
                                    <label className="text-sm font-semibold">Payload</label>
                                    {hasPayload && featureFlag.filters?.payloads?.['true'] ? (
                                        <JSONEditorInput readOnly value={featureFlag.filters.payloads['true']} />
                                    ) : (
                                        <div className="text-sm text-muted p-3 rounded border border-dashed bg-surface-secondary">
                                            No payload configured
                                        </div>
                                    )}
                                </div>
                            </div>
                        </EditableOverviewSection>
                    )}

                    {!featureFlag.is_remote_configuration && (
                        <>
                            {featureFlag.filters.super_groups && featureFlag.filters.super_groups.length > 0 && (
                                <div className="rounded border p-4 bg-bg-light">
                                    <FeatureFlagSuperConditionsReadonly
                                        id={String(featureFlag.id)}
                                        flagKey={featureFlag.key}
                                        filters={featureFlag.filters}
                                        earlyAccessFeatures={
                                            (featureFlag.features ?? undefined) as
                                                | { id: string; flagKey: string }[]
                                                | undefined
                                        }
                                        isDisabled={!featureFlag.active}
                                    />
                                </div>
                            )}
                            <EditableOverviewSection
                                disabledReason={
                                    featureFlag.experiment_set && featureFlag.experiment_set.length > 0
                                        ? 'Release conditions are managed by the linked experiment'
                                        : undefined
                                }
                            >
                                <FeatureFlagReleaseConditionsReadonly
                                    id={String(featureFlag.id)}
                                    filters={featureFlag.filters}
                                    isDisabled={!featureFlag.active}
                                    evaluationRuntime={featureFlag.evaluation_runtime}
                                />
                            </EditableOverviewSection>
                        </>
                    )}
                </div>
            </div>

            <LemonCollapse
                className="bg-bg-light"
                panels={[
                    {
                        key: 'implementation',
                        header: 'How to implement',
                        content: (
                            <div className="flex flex-col gap-4">
                                <p className="text-sm text-muted m-0">
                                    Use the following code to implement this feature flag.
                                </p>
                                <FeatureFlagInstructions featureFlag={featureFlag} />
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
