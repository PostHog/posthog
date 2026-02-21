import './FeatureFlag.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconCode, IconFlag, IconGlobe, IconList, IconMessage, IconServer } from '@posthog/icons'
import {
    LemonButton,
    LemonCollapse,
    LemonDialog,
    LemonDivider,
    LemonSwitch,
    LemonTag,
    Lettermark,
    LettermarkColor,
} from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import ViewRecordingsPlaylistButton from 'lib/components/ViewRecordingButton/ViewRecordingsPlaylistButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { alphabet } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { FeatureFlagEvaluationRuntime, FeatureFlagType } from '~/types'

import { FeatureFlagEvaluationTags } from './FeatureFlagEvaluationTags'
import { FeatureFlagInstructions } from './FeatureFlagInstructions'
import { FeatureFlagReleaseConditionsReadonly } from './FeatureFlagReleaseConditionsReadonly'
import { JSONEditorInput } from './JSONEditorInput'
import { RecentFeatureFlagInsights } from './RecentFeatureFlagInsightsCard'
import { featureFlagLogic } from './featureFlagLogic'

interface FeatureFlagOverviewV2Props {
    featureFlag: FeatureFlagType
    onGetFeedback?: (variantKey?: string) => void
}

export function FeatureFlagOverviewV2({ featureFlag, onGetFeedback }: FeatureFlagOverviewV2Props): JSX.Element {
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const { recordingFilterForFlag } = useValues(featureFlagLogic)
    const { toggleFeatureFlagActive } = useActions(featureFlagLogic)
    const { addProductIntentForCrossSell } = useActions(teamLogic)

    const hasEvaluationTags = !!featureFlags[FEATURE_FLAGS.FLAG_EVALUATION_TAGS]
    const hasEvaluationRuntimes = !!featureFlags[FEATURE_FLAGS.FLAG_EVALUATION_RUNTIMES]

    const multivariateEnabled = !!featureFlag.filters?.multivariate
    const variants = featureFlag.filters?.multivariate?.variants || []
    const hasPayload = !!featureFlag.filters?.payloads?.['true']
    const hasTags =
        (featureFlag.tags && featureFlag.tags.length > 0) ||
        (featureFlag.evaluation_tags && featureFlag.evaluation_tags.length > 0)

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

    // Determine flag type for display
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

    // Get evaluation runtime display
    const getEvaluationRuntimeDisplay = (): { icon: JSX.Element; label: string; tag: string } => {
        switch (featureFlag.evaluation_runtime) {
            case FeatureFlagEvaluationRuntime.CLIENT:
                return {
                    icon: <IconList className="text-lg text-muted" />,
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

    // All variant panels open by default
    const allVariantKeys = variants.map((_, index) => `variant-${index}`)

    return (
        <div className="flex flex-col gap-6">
            {/* Top section: Frozen edit view (two-column layout) */}
            <div className="flex gap-4 flex-wrap items-start">
                {/* Left column */}
                <div className="flex-1 min-w-[20rem] flex flex-col gap-4">
                    {/* Main settings card */}
                    <div className="rounded border p-4 bg-bg-light flex flex-col gap-3">
                        {/* Enabled toggle */}
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
                                label={featureFlag.active ? 'Enabled' : 'Disabled'}
                                bordered
                                fullWidth
                            />
                        )}
                    </div>

                    {/* Advanced options card */}
                    <div className="rounded border p-4 bg-bg-light flex flex-col gap-4">
                        <div className="font-semibold">Advanced options</div>

                        {/* Tags section */}
                        <div className="flex flex-col gap-2">
                            <label className="text-sm font-medium">
                                {hasEvaluationTags ? 'Tags & evaluation contexts' : 'Tags'}
                            </label>
                            {hasEvaluationTags && hasTags ? (
                                <FeatureFlagEvaluationTags
                                    tags={featureFlag.tags || []}
                                    evaluationTags={featureFlag.evaluation_tags || []}
                                    flagId={featureFlag.id}
                                    context="static"
                                />
                            ) : featureFlag.tags && featureFlag.tags.length > 0 ? (
                                <ObjectTags tags={featureFlag.tags} staticOnly />
                            ) : (
                                <span className="text-muted">No tags</span>
                            )}
                        </div>

                        {hasEvaluationRuntimes && (
                            <>
                                <LemonDivider className="my-1" />

                                {/* Evaluation runtime */}
                                <div className="flex flex-col gap-2">
                                    <label className="text-sm font-medium">Evaluation runtime</label>
                                    <div className="flex items-center gap-2">
                                        {evaluationRuntimeDisplay.icon}
                                        <span className="font-medium text-sm">{evaluationRuntimeDisplay.label}</span>
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

                                {/* Persistence */}
                                <div className="flex flex-col gap-2">
                                    <label className="text-sm font-medium">Persistence</label>
                                    <span className="text-sm text-muted">
                                        {featureFlag.ensure_experience_continuity ? (
                                            <>
                                                This flag <b className="text-default">persists</b> across authentication
                                                steps
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

                    {/* Insights card - only for non-remote config flags */}
                    {!featureFlag.is_remote_configuration && (
                        <div className="rounded border p-4 bg-bg-light flex flex-col gap-3">
                            <div className="font-semibold">Insights</div>
                            <RecentFeatureFlagInsights />

                            {/* Related actions */}
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

                {/* Right column */}
                <div className="flex-2 min-w-[30rem] flex flex-col gap-4">
                    {/* Flag type card */}
                    <div className="rounded border p-4 bg-bg-light flex flex-col gap-4">
                        {/* Type indicator */}
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

                        {/* Variants section - multivariate only */}
                        {multivariateEnabled && variants.length > 0 && (
                            <div className="flex flex-col gap-2">
                                <label className="text-sm font-medium text-muted">Variants</label>
                                <LemonCollapse
                                    multiple
                                    defaultActiveKeys={allVariantKeys}
                                    panels={variants.map((variant, index) => ({
                                        key: `variant-${index}`,
                                        header: (
                                            <div className="flex gap-2 items-center">
                                                <Lettermark
                                                    name={alphabet[index] ?? String(index + 1)}
                                                    color={LettermarkColor.Gray}
                                                    size="small"
                                                />
                                                <span className="text-sm font-medium">
                                                    {variant.key || `Variant ${index + 1}`}
                                                </span>
                                                <span className="text-xs text-muted">
                                                    ({variant.rollout_percentage || 0}%)
                                                </span>
                                            </div>
                                        ),
                                        content: (
                                            <div className="flex flex-col gap-3">
                                                <div className="flex flex-col gap-1">
                                                    <label className="text-xs font-medium text-muted">
                                                        Variant key
                                                    </label>
                                                    <div className="font-mono text-sm">{variant.key}</div>
                                                </div>

                                                <div className="flex flex-col gap-1">
                                                    <label className="text-xs font-medium text-muted">
                                                        Rollout percentage
                                                    </label>
                                                    <div className="text-sm font-semibold">
                                                        {variant.rollout_percentage || 0}%
                                                    </div>
                                                </div>

                                                {variant.name && (
                                                    <div className="flex flex-col gap-1">
                                                        <label className="text-xs font-medium text-muted">
                                                            Description
                                                        </label>
                                                        <div className="text-sm">{variant.name}</div>
                                                    </div>
                                                )}

                                                {featureFlag.filters?.payloads?.[variant.key] && (
                                                    <div className="flex flex-col gap-1">
                                                        <label className="text-xs font-medium text-muted">
                                                            Payload
                                                        </label>
                                                        <JSONEditorInput
                                                            readOnly
                                                            value={featureFlag.filters.payloads[variant.key]}
                                                        />
                                                    </div>
                                                )}
                                            </div>
                                        ),
                                    }))}
                                />
                            </div>
                        )}

                        {/* Payload section - boolean and remote config */}
                        {!multivariateEnabled && (
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
                        )}
                    </div>

                    {/* Release conditions card - skip for remote config */}
                    {!featureFlag.is_remote_configuration && (
                        <div className="rounded border p-4 bg-bg-light">
                            <FeatureFlagReleaseConditionsReadonly
                                id={String(featureFlag.id)}
                                filters={featureFlag.filters}
                            />
                        </div>
                    )}
                </div>
            </div>

            {/* Implementation section */}
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
