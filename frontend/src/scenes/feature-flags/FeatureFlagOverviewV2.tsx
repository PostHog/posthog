import './FeatureFlag.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import {
    IconBalance,
    IconCode,
    IconFlag,
    IconGlobe,
    IconLaptop,
    IconList,
    IconMessage,
    IconPlus,
    IconServer,
    IconTrash,
} from '@posthog/icons'
import {
    LemonButton,
    LemonCollapse,
    LemonDialog,
    LemonDivider,
    LemonInput,
    LemonLabel,
    LemonSelect,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
    Lettermark,
    LettermarkColor,
} from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import ViewRecordingsPlaylistButton from 'lib/components/ViewRecordingButton/ViewRecordingsPlaylistButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { alphabet } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import { tagsModel } from '~/models/tagsModel'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { FeatureFlagEvaluationRuntime, FeatureFlagType, MultivariateFlagVariant } from '~/types'

import { EditableOverviewSection } from './EditableOverviewSection'
import { FeatureFlagEvaluationTags } from './FeatureFlagEvaluationTags'
import { FeatureFlagInstructions } from './FeatureFlagInstructions'
import { featureFlagLogic } from './featureFlagLogic'
import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'
import {
    FeatureFlagReleaseConditionsReadonly,
    FeatureFlagSuperConditionsReadonly,
} from './FeatureFlagReleaseConditionsReadonly'
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

interface VariantsSectionProps {
    featureFlag: FeatureFlagType
    variants: MultivariateFlagVariant[]
    isEditing: boolean
    sectionDraft: Partial<FeatureFlagType> | null
    updateSectionDraft: (draft: Partial<FeatureFlagType>) => void
    allVariantKeys: string[]
}

function VariantsSection({
    featureFlag,
    variants: originalVariants,
    isEditing,
    sectionDraft,
    updateSectionDraft,
    allVariantKeys,
}: VariantsSectionProps): JSX.Element {
    const draftVariants: MultivariateFlagVariant[] = sectionDraft?.filters?.multivariate?.variants ?? originalVariants
    const draftPayloads = sectionDraft?.filters?.payloads ?? featureFlag.filters?.payloads ?? {}

    const updateVariant = (
        index: number,
        field: 'key' | 'name' | 'rollout_percentage',
        value: string | number
    ): void => {
        const coercedValue = field === 'rollout_percentage' ? Number(value) || 0 : String(value)
        const currentVariants = [...draftVariants]
        const oldKey = currentVariants[index]?.key
        currentVariants[index] = { ...currentVariants[index], [field]: coercedValue }

        let updatedPayloads = { ...draftPayloads }
        if (field === 'key' && oldKey && oldKey !== coercedValue) {
            const existingPayload = updatedPayloads[oldKey]
            if (existingPayload !== undefined) {
                delete updatedPayloads[oldKey]
                updatedPayloads[coercedValue as string] = existingPayload
            }
        }

        updateSectionDraft({
            filters: {
                ...featureFlag.filters,
                ...sectionDraft?.filters,
                multivariate: {
                    ...featureFlag.filters?.multivariate,
                    ...sectionDraft?.filters?.multivariate,
                    variants: currentVariants,
                },
                payloads: updatedPayloads,
            },
        })
    }

    const updateVariantPayload = (index: number, value: string | undefined): void => {
        const variantKey = draftVariants[index]?.key
        if (!variantKey) {
            return
        }
        const currentPayloads = { ...draftPayloads }
        if (value === '' || value === undefined) {
            delete currentPayloads[variantKey]
        } else {
            currentPayloads[variantKey] = value
        }
        updateSectionDraft({
            filters: {
                ...featureFlag.filters,
                ...sectionDraft?.filters,
                payloads: currentPayloads,
            },
        })
    }

    const addVariant = (): void => {
        const currentVariants = [...draftVariants]
        currentVariants.push({ key: '', name: '', rollout_percentage: 0 })
        updateSectionDraft({
            filters: {
                ...featureFlag.filters,
                ...sectionDraft?.filters,
                multivariate: {
                    ...featureFlag.filters?.multivariate,
                    ...sectionDraft?.filters?.multivariate,
                    variants: currentVariants,
                },
            },
        })
    }

    const removeVariant = (index: number): void => {
        const currentVariants = [...draftVariants]
        const removedVariant = currentVariants[index]
        currentVariants.splice(index, 1)

        const currentPayloads = { ...draftPayloads }
        if (removedVariant?.key) {
            delete currentPayloads[removedVariant.key]
        }

        updateSectionDraft({
            filters: {
                ...featureFlag.filters,
                ...sectionDraft?.filters,
                multivariate: {
                    ...featureFlag.filters?.multivariate,
                    ...sectionDraft?.filters?.multivariate,
                    variants: currentVariants,
                },
                payloads: currentPayloads,
            },
        })
    }

    const distributeVariantsEqually = (): void => {
        const currentVariants = [...draftVariants]
        const numVariants = currentVariants.length
        if (numVariants > 0 && numVariants <= 100) {
            const percentageRounded = Math.round(100 / numVariants)
            const totalRounded = percentageRounded * numVariants
            const delta = totalRounded - 100
            currentVariants.forEach((variant, index) => {
                currentVariants[index] = { ...variant, rollout_percentage: percentageRounded }
            })
            currentVariants[numVariants - 1] = {
                ...currentVariants[numVariants - 1],
                rollout_percentage: percentageRounded - delta,
            }
        }
        updateSectionDraft({
            filters: {
                ...featureFlag.filters,
                ...sectionDraft?.filters,
                multivariate: {
                    ...featureFlag.filters?.multivariate,
                    ...sectionDraft?.filters?.multivariate,
                    variants: currentVariants,
                },
            },
        })
    }

    const displayVariants = isEditing ? draftVariants : originalVariants
    const displayPayloads = isEditing ? draftPayloads : (featureFlag.filters?.payloads ?? {})

    if (isEditing) {
        return (
            <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                    <LemonLabel>Variants</LemonLabel>
                    <LemonButton
                        size="small"
                        icon={<IconBalance />}
                        onClick={distributeVariantsEqually}
                        tooltip="Distribute rollout percentages equally"
                    />
                </div>

                <LemonCollapse
                    multiple
                    defaultActiveKeys={allVariantKeys}
                    panels={displayVariants.map((variant, index) => ({
                        key: `variant-${index}`,
                        header: (
                            <div className="flex gap-2 items-center">
                                <Lettermark
                                    name={alphabet[index] ?? String(index + 1)}
                                    color={LettermarkColor.Gray}
                                    size="small"
                                />
                                <span className="text-sm font-medium">{variant.key || `Variant ${index + 1}`}</span>
                                <span className="text-xs text-muted">({variant.rollout_percentage || 0}%)</span>
                            </div>
                        ),
                        content: (
                            <div className="flex flex-col gap-2">
                                <LemonLabel>Variant key</LemonLabel>
                                <LemonInput
                                    placeholder="Enter a variant key - e.g. control, test, variant_1"
                                    value={variant.key}
                                    onChange={(value) => updateVariant(index, 'key', value)}
                                />

                                <LemonLabel>Rollout percentage</LemonLabel>
                                <LemonInput
                                    type="number"
                                    min={0}
                                    max={100}
                                    value={variant.rollout_percentage || 0}
                                    onChange={(value) =>
                                        updateVariant(index, 'rollout_percentage', parseInt(value?.toString() || '0'))
                                    }
                                    suffix={<span>%</span>}
                                />

                                <LemonLabel>Description</LemonLabel>
                                <LemonTextArea
                                    placeholder="Enter an optional description for the variant"
                                    value={variant.name || ''}
                                    onChange={(value) => updateVariant(index, 'name', value)}
                                />

                                <LemonLabel>Payload</LemonLabel>
                                <JSONEditorInput
                                    onChange={(value) => updateVariantPayload(index, value)}
                                    value={displayPayloads[variant.key]}
                                    placeholder='{"key": "value"}'
                                />

                                {displayVariants.length > 1 && <LemonDivider />}
                                {displayVariants.length > 1 && (
                                    <LemonButton
                                        type="secondary"
                                        status="danger"
                                        size="small"
                                        icon={<IconTrash />}
                                        onClick={() => {
                                            const variantKey = variant.key || `Variant ${index + 1}`
                                            const hasPayload = !!displayPayloads[variant.key]
                                            LemonDialog.open({
                                                title: `Remove variant "${variantKey}"?`,
                                                description: hasPayload
                                                    ? 'This variant has a payload configured. Both the variant and its payload will be deleted.'
                                                    : 'This action cannot be undone.',
                                                primaryButton: {
                                                    children: 'Remove variant',
                                                    status: 'danger',
                                                    onClick: () => removeVariant(index),
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                },
                                            })
                                        }}
                                    >
                                        Remove variant
                                    </LemonButton>
                                )}
                            </div>
                        ),
                    }))}
                />

                <div>
                    <LemonButton type="secondary" icon={<IconPlus />} onClick={addVariant}>
                        Add variant
                    </LemonButton>
                </div>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <label className="text-sm font-medium text-muted">Variants</label>
            <LemonCollapse
                multiple
                defaultActiveKeys={allVariantKeys}
                panels={displayVariants.map((variant, index) => ({
                    key: `variant-${index}`,
                    header: (
                        <div className="flex gap-2 items-center">
                            <Lettermark
                                name={alphabet[index] ?? String(index + 1)}
                                color={LettermarkColor.Gray}
                                size="small"
                            />
                            <span className="text-sm font-medium">{variant.key || `Variant ${index + 1}`}</span>
                            <span className="text-xs text-muted">({variant.rollout_percentage || 0}%)</span>
                        </div>
                    ),
                    content: (
                        <div className="flex flex-col gap-3">
                            <div className="flex flex-col gap-1">
                                <label className="text-xs font-medium text-muted">Variant key</label>
                                <div className="font-mono text-sm">{variant.key}</div>
                            </div>

                            <div className="flex flex-col gap-1">
                                <label className="text-xs font-medium text-muted">Rollout percentage</label>
                                <div className="text-sm font-semibold">{variant.rollout_percentage || 0}%</div>
                            </div>

                            {variant.name && (
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs font-medium text-muted">Description</label>
                                    <div className="text-sm">{variant.name}</div>
                                </div>
                            )}

                            {displayPayloads[variant.key] && (
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs font-medium text-muted">Payload</label>
                                    <JSONEditorInput readOnly value={displayPayloads[variant.key]} />
                                </div>
                            )}
                        </div>
                    ),
                }))}
            />
        </div>
    )
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

    // All variant panels open by default
    const allVariantKeys = variants.map((_, index) => `variant-${index}`)

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
                                label={featureFlag.active ? 'Enabled' : 'Disabled'}
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
                                                        featureFlag.ensure_experience_continuity
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
                                <VariantsSection
                                    featureFlag={featureFlag}
                                    variants={variants}
                                    isEditing={isEditing}
                                    sectionDraft={sectionDraft}
                                    updateSectionDraft={updateSectionDraft}
                                    allVariantKeys={allVariantKeys}
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
                                            value={
                                                sectionDraft?.filters?.payloads?.['true'] ??
                                                featureFlag.filters?.payloads?.['true'] ??
                                                ''
                                            }
                                            onChange={(val) =>
                                                updateSectionDraft({
                                                    filters: {
                                                        ...featureFlag.filters,
                                                        payloads: {
                                                            ...featureFlag.filters?.payloads,
                                                            true: val,
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
