import './FeatureFlag.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconCode, IconFlag, IconGlobe, IconLaptop, IconList, IconMessage, IconServer } from '@posthog/icons'
import {
    LemonButton,
    LemonCollapse,
    LemonDialog,
    LemonDivider,
    LemonSelect,
    LemonSwitch,
    LemonTag,
} from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import ViewRecordingsPlaylistButton from 'lib/components/ViewRecordingButton/ViewRecordingsPlaylistButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { tagsModel } from '~/models/tagsModel'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { FeatureFlagEvaluationRuntime, FeatureFlagType } from '~/types'

import { EditableOverviewSection } from './EditableOverviewSection'
import { FeatureFlagEvaluationTags } from './FeatureFlagEvaluationTags'
import { FeatureFlagInstructions } from './FeatureFlagInstructions'
import { featureFlagLogic } from './featureFlagLogic'
import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'
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
    evaluationTags: string[]
    flagId: number | null
    hasEvaluationTags: boolean
}

function TagsDisplay({ tags, evaluationTags, flagId, hasEvaluationTags }: TagsDisplayProps): JSX.Element {
    const hasTags = tags.length > 0 || evaluationTags.length > 0

    if (hasEvaluationTags && hasTags) {
        return (
            <FeatureFlagEvaluationTags tags={tags} evaluationTags={evaluationTags} flagId={flagId} context="static" />
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
    const { recordingFilterForFlag, sectionDraft } = useValues(featureFlagLogic)
    const { toggleFeatureFlagActive, updateSectionDraft } = useActions(featureFlagLogic)
    const { addProductIntentForCrossSell } = useActions(teamLogic)
    const { tags: availableTags } = useValues(tagsModel)

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
                            <LemonSwitch
                                checked={featureFlag.active}
                                onChange={handleToggleClick}
                                label="Enable feature flag"
                                bordered
                                fullWidth
                            />
                        )}
                    </div>

                    <EditableOverviewSection section="advanced_options">
                        {({ isEditing }) => (
                            <div className="flex flex-col gap-4">
                                <div className="font-semibold">Advanced options</div>

                                <div className="flex flex-col gap-2">
                                    <label className="text-sm font-medium">
                                        {hasEvaluationTags ? 'Tags & evaluation contexts' : 'Tags'}
                                    </label>
                                    {isEditing ? (
                                        hasEvaluationTags ? (
                                            <FeatureFlagEvaluationTags
                                                tags={sectionDraft?.tags ?? featureFlag.tags ?? []}
                                                evaluationTags={
                                                    sectionDraft?.evaluation_tags ?? featureFlag.evaluation_tags ?? []
                                                }
                                                context="form"
                                                onChange={(tags, evaluationTags) =>
                                                    updateSectionDraft({ tags, evaluation_tags: evaluationTags })
                                                }
                                                tagsAvailable={availableTags.filter(
                                                    (tag: string) =>
                                                        !(sectionDraft?.tags ?? featureFlag.tags ?? []).includes(tag)
                                                )}
                                            />
                                        ) : (
                                            <ObjectTags
                                                tags={sectionDraft?.tags ?? featureFlag.tags ?? []}
                                                onChange={(tags) => updateSectionDraft({ tags })}
                                                saving={false}
                                                tagsAvailable={availableTags.filter(
                                                    (tag: string) =>
                                                        !(sectionDraft?.tags ?? featureFlag.tags ?? []).includes(tag)
                                                )}
                                            />
                                        )
                                    ) : (
                                        <TagsDisplay
                                            tags={featureFlag.tags || []}
                                            evaluationTags={featureFlag.evaluation_tags || []}
                                            flagId={featureFlag.id}
                                            hasEvaluationTags={hasEvaluationTags}
                                        />
                                    )}
                                </div>

                                {hasEvaluationRuntimes && (
                                    <>
                                        <LemonDivider className="my-1" />

                                        <div className="flex flex-col gap-2">
                                            <label className="text-sm font-medium">Evaluation runtime</label>
                                            {isEditing ? (
                                                <LemonSelect
                                                    fullWidth
                                                    value={
                                                        sectionDraft?.evaluation_runtime ??
                                                        featureFlag.evaluation_runtime
                                                    }
                                                    onChange={(value) =>
                                                        updateSectionDraft({ evaluation_runtime: value })
                                                    }
                                                    options={[
                                                        {
                                                            label: 'Both client and server',
                                                            value: FeatureFlagEvaluationRuntime.ALL,
                                                            icon: <IconGlobe />,
                                                        },
                                                        {
                                                            label: 'Client-side only',
                                                            value: FeatureFlagEvaluationRuntime.CLIENT,
                                                            icon: <IconLaptop />,
                                                        },
                                                        {
                                                            label: 'Server-side only',
                                                            value: FeatureFlagEvaluationRuntime.SERVER,
                                                            icon: <IconServer />,
                                                        },
                                                    ]}
                                                />
                                            ) : (
                                                <div className="flex items-center gap-2">
                                                    {evaluationRuntimeDisplay.icon}
                                                    <span className="font-medium text-sm">
                                                        {evaluationRuntimeDisplay.label}
                                                    </span>
                                                    <LemonTag type="muted" size="small">
                                                        {evaluationRuntimeDisplay.tag}
                                                    </LemonTag>
                                                </div>
                                            )}
                                        </div>
                                    </>
                                )}

                                {!featureFlag.is_remote_configuration && (
                                    <>
                                        <LemonDivider className="my-1" />

                                        <div className="flex flex-col gap-2">
                                            <label className="text-sm font-medium">Persistence</label>
                                            {isEditing ? (
                                                <LemonSwitch
                                                    checked={
                                                        sectionDraft?.ensure_experience_continuity ??
                                                        featureFlag.ensure_experience_continuity ??
                                                        false
                                                    }
                                                    onChange={(checked) =>
                                                        updateSectionDraft({
                                                            ensure_experience_continuity: checked,
                                                        })
                                                    }
                                                    bordered
                                                    fullWidth
                                                    label="Persist flag across authentication steps"
                                                />
                                            ) : (
                                                <span className="text-sm text-muted">
                                                    {featureFlag.ensure_experience_continuity ? (
                                                        <>
                                                            This flag <b className="text-default">persists</b> across
                                                            authentication steps
                                                        </>
                                                    ) : (
                                                        <>
                                                            This flag <b className="text-default">does not persist</b>{' '}
                                                            across authentication steps
                                                        </>
                                                    )}
                                                </span>
                                            )}
                                        </div>
                                    </>
                                )}
                            </div>
                        )}
                    </EditableOverviewSection>

                    {!featureFlag.is_remote_configuration && (
                        <div className="rounded border p-4 bg-bg-light flex flex-col gap-3">
                            <div className="font-semibold">Insights</div>
                            <RecentFeatureFlagInsights />

                            <div className="flex flex-col gap-3 mt-2 pt-3 border-t border-border-light">
                                <div className="flex items-center justify-between">
                                    <span className="text-sm text-muted">
                                        Watch recordings of users exposed to this flag
                                    </span>
                                    <ViewRecordingsPlaylistButton
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
                                    <div className="flex items-center justify-between">
                                        <span className="text-sm text-muted">
                                            Gather feedback from users who see this flag
                                        </span>
                                        <LemonButton
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
                    <div className="rounded border p-4 bg-bg-light flex flex-col gap-2">
                        <label className="text-sm font-semibold">Flag type</label>
                        <div className="flex items-center gap-3 p-3 rounded border bg-surface-secondary">
                            {flagTypeDisplay.icon}
                            <div className="flex flex-col">
                                <span className="font-medium">{flagTypeDisplay.label}</span>
                                <span className="text-xs text-muted">{flagTypeDisplay.description}</span>
                            </div>
                        </div>
                    </div>

                    {multivariateEnabled && variants.length > 0 && (
                        <EditableOverviewSection
                            section="variants"
                            disabledReason={
                                featureFlag.experiment_set && featureFlag.experiment_set.length > 0
                                    ? 'Variants are managed by the linked experiment'
                                    : undefined
                            }
                        >
                            {({ isEditing }) => (
                                <FeatureFlagVariantsSection
                                    featureFlag={featureFlag}
                                    variants={variants}
                                    isEditing={isEditing}
                                    sectionDraft={sectionDraft}
                                />
                            )}
                        </EditableOverviewSection>
                    )}

                    {!multivariateEnabled && (
                        <EditableOverviewSection section="payload">
                            {({ isEditing }) => (
                                <div className="flex flex-col gap-2">
                                    <label className="text-sm font-semibold">Payload</label>
                                    {isEditing ? (
                                        <JSONEditorInput
                                            placeholder='Examples: "string value", true, {"key": "value"}'
                                            value={
                                                sectionDraft?.filters?.payloads?.['true'] ??
                                                featureFlag.filters?.payloads?.['true'] ??
                                                ''
                                            }
                                            onChange={(val) =>
                                                updateSectionDraft({
                                                    filters: {
                                                        ...featureFlag.filters,
                                                        ...sectionDraft?.filters,
                                                        payloads: {
                                                            ...featureFlag.filters?.payloads,
                                                            ...sectionDraft?.filters?.payloads,
                                                            true: val ?? '',
                                                        },
                                                    },
                                                })
                                            }
                                        />
                                    ) : hasPayload && featureFlag.filters?.payloads?.['true'] ? (
                                        <JSONEditorInput readOnly value={featureFlag.filters.payloads['true']} />
                                    ) : (
                                        <div className="text-sm text-muted p-3 rounded border border-dashed bg-surface-secondary">
                                            No payload configured
                                        </div>
                                    )}
                                </div>
                            )}
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
                                section="release_conditions"
                                disabledReason={
                                    featureFlag.experiment_set && featureFlag.experiment_set.length > 0
                                        ? 'Release conditions are managed by the linked experiment'
                                        : undefined
                                }
                            >
                                {({ isEditing }) =>
                                    isEditing ? (
                                        <FeatureFlagReleaseConditionsCollapsible
                                            id={String(featureFlag.id)}
                                            filters={sectionDraft?.filters ?? featureFlag.filters}
                                            onChange={(filters) => updateSectionDraft({ filters })}
                                            nonEmptyFeatureFlagVariants={
                                                featureFlag.filters?.multivariate?.variants?.filter((v) => !!v.key) ??
                                                []
                                            }
                                            isDisabled={!featureFlag.active}
                                        />
                                    ) : (
                                        <FeatureFlagReleaseConditionsReadonly
                                            id={String(featureFlag.id)}
                                            filters={featureFlag.filters}
                                            isDisabled={!featureFlag.active}
                                        />
                                    )
                                }
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
