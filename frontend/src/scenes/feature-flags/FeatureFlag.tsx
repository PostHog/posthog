import './FeatureFlag.scss'

import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { PostHogFeature } from 'posthog-js/react'
import { useEffect, useState } from 'react'

import {
    IconBalance,
    IconCollapse,
    IconExpand,
    IconGlobe,
    IconInfo,
    IconLaptop,
    IconPlus,
    IconRewindPlay,
    IconServer,
    IconTrash,
} from '@posthog/icons'
import { LemonDialog, LemonSegmentedButton, LemonSkeleton, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AccessControlledLemonButton } from 'lib/components/AccessControlledLemonButton'
import { AccessDenied } from 'lib/components/AccessDenied'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { NotFound } from 'lib/components/NotFound'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { alphabet, capitalizeFirstLetter } from 'lib/utils'
import { ProductIntentContext, addProductIntent } from 'lib/utils/product-intents'
import { FeatureFlagPermissions } from 'scenes/FeatureFlagPermissions'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { EmptyDashboardComponent } from 'scenes/dashboard/EmptyDashboardComponent'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { UTM_TAGS } from 'scenes/feature-flags/FeatureFlagSnippets'
import { JSONEditorInput } from 'scenes/feature-flags/JSONEditorInput'
import { concatWithPunctuation } from 'scenes/insights/utils'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { SceneExport } from 'scenes/sceneTypes'
import { SURVEY_CREATED_SOURCE } from 'scenes/surveys/constants'
import { captureMaxAISurveyCreationException } from 'scenes/surveys/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { tagsModel } from '~/models/tagsModel'
import { Query } from '~/queries/Query/Query'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { NodeKind } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ActivityScope,
    AnyPropertyFilter,
    AvailableFeature,
    DashboardPlacement,
    DashboardType,
    EarlyAccessFeatureStage,
    FeatureFlagEvaluationRuntime,
    FeatureFlagGroupType,
    FeatureFlagType,
    MultivariateFlagVariant,
    ProductKey,
    PropertyFilterType,
    PropertyOperator,
    QueryBasedInsightModel,
    ReplayTabs,
} from '~/types'

import { AnalysisTab } from './FeatureFlagAnalysisTab'
import { FeatureFlagAutoRollback } from './FeatureFlagAutoRollout'
import { FeatureFlagCodeExample } from './FeatureFlagCodeExample'
import FeatureFlagProjects from './FeatureFlagProjects'
import { FeatureFlagReleaseConditions } from './FeatureFlagReleaseConditions'
import FeatureFlagSchedule from './FeatureFlagSchedule'
import { FeatureFlagStatusIndicator } from './FeatureFlagStatusIndicator'
import { RecentFeatureFlagInsights } from './RecentFeatureFlagInsightsCard'
import { FeatureFlagLogicProps, featureFlagLogic, getRecordingFilterForFlagVariant } from './featureFlagLogic'
import { FeatureFlagsTab, featureFlagsLogic } from './featureFlagsLogic'

// Utility function to create MaxTool configuration for feature flag survey creation
export function createMaxToolSurveyConfig(
    featureFlag: FeatureFlagType,
    user: any,
    multivariateEnabled: boolean,
    variants: any[]
): {
    identifier: 'create_survey'
    active: boolean
    initialMaxPrompt: string
    suggestions: string[]
    context: Record<string, any>
    callback: (toolOutput: { survey_id?: string; survey_name?: string; error?: string }) => void
} {
    return {
        identifier: 'create_survey' as const,
        active: Boolean(user?.uuid),
        initialMaxPrompt: `Create a survey to collect feedback about the "${featureFlag.key}" feature flag${featureFlag.name ? ` (${featureFlag.name})` : ''}${multivariateEnabled && variants?.length > 0 ? ` which has variants: ${variants.map((v) => `"${v.key}"`).join(', ')}` : ''}`,
        suggestions:
            multivariateEnabled && variants?.length > 0
                ? [
                      `Create a feedback survey comparing variants of the "${featureFlag.key}" feature flag`,
                      `Create a survey for users who saw the "${variants[0]?.key}" variant of the "${featureFlag.key}" feature flag`,
                      `Create an A/B test survey asking users to compare the "${featureFlag.key}" feature flag variants`,
                      `Create a survey to understand which variant of the "${featureFlag.key}" feature flag performs better`,
                      `Create a survey targeting all variants of the "${featureFlag.key}" feature flag to gather overall feedback`,
                  ]
                : [
                      `Create a feedback survey for users who see the "${featureFlag.key}" feature flag`,
                      `Create an NPS survey for users exposed to the "${featureFlag.key}" feature flag`,
                      `Create a satisfaction survey asking about the "${featureFlag.key}" feature flag experience`,
                      `Create a survey to understand user reactions to the "${featureFlag.key}" feature flag`,
                  ],
        context: {
            user_id: user?.uuid,
            feature_flag_key: featureFlag.key,
            feature_flag_id: featureFlag.id,
            feature_flag_name: featureFlag.name,
            target_feature_flag: featureFlag.key,
            survey_purpose: 'collect_feedback_for_feature_flag',
            is_multivariate: multivariateEnabled,
            variants:
                multivariateEnabled && variants?.length > 0
                    ? variants.map((v) => ({
                          key: v.key,
                          name: v.name || '',
                          rollout_percentage: v.rollout_percentage,
                      }))
                    : [],
            variant_count: variants?.length || 0,
        },
        callback: (toolOutput: { survey_id?: string; survey_name?: string; error?: string }) => {
            addProductIntent({
                product_type: ProductKey.SURVEYS,
                intent_context: ProductIntentContext.SURVEY_CREATED,
                metadata: {
                    survey_id: toolOutput.survey_id,
                    source: SURVEY_CREATED_SOURCE.FEATURE_FLAGS,
                    created_successfully: !toolOutput?.error,
                },
            })

            if (toolOutput?.error || !toolOutput?.survey_id) {
                return captureMaxAISurveyCreationException(toolOutput.error, SURVEY_CREATED_SOURCE.FEATURE_FLAGS)
            }

            // Redirect to the new survey
            router.actions.push(urls.survey(toolOutput.survey_id))
        },
    }
}

export const scene: SceneExport<FeatureFlagLogicProps> = {
    component: FeatureFlag,
    logic: featureFlagLogic,
    paramsToProps: ({ params: { id } }) => ({
        id: id && id !== 'new' ? parseInt(id) : 'new',
    }),
    settingSectionId: 'environment-feature-flags',
}

function focusVariantKeyField(index: number): void {
    setTimeout(
        () => document.querySelector<HTMLElement>(`.VariantFormList input[data-key-index="${index}"]`)?.focus(),
        50
    )
}

export function FeatureFlag({ id }: FeatureFlagLogicProps): JSX.Element {
    const {
        props,
        featureFlag,
        featureFlagLoading,
        featureFlagMissing,
        isEditingFlag,
        newCohortLoading,
        activeTab,
        accessDeniedToFeatureFlag,
        multivariateEnabled,
        variants,
    } = useValues(featureFlagLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const {
        deleteFeatureFlag,
        restoreFeatureFlag,
        editFeatureFlag,
        loadFeatureFlag,
        saveFeatureFlag,
        createStaticCohort,
        setFeatureFlagFilters,
        setActiveTab,
    } = useActions(featureFlagLogic)

    const { earlyAccessFeaturesList } = useValues(featureFlagLogic)

    const { tags } = useValues(tagsModel)
    const { hasAvailableFeature, user } = useValues(userLogic)

    // whether the key for an existing flag is being changed
    const [hasKeyChanged, setHasKeyChanged] = useState(false)

    // Initialize MaxTool hook for survey creation
    const { openMax } = useMaxTool(createMaxToolSurveyConfig(featureFlag, user, multivariateEnabled, variants))

    const [advancedSettingsExpanded, setAdvancedSettingsExpanded] = useState(false)

    const isNewFeatureFlag = id === 'new' || id === undefined

    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    if (featureFlagMissing) {
        return <NotFound object="feature flag" />
    }

    if (featureFlagLoading) {
        return (
            <div className="deprecated-space-y-2">
                <LemonSkeleton active className="h-4 w-2/5" />
                <LemonSkeleton active className="h-4 w-full" />
                <LemonSkeleton active className="h-4 w-full" />
                <LemonSkeleton active className="h-4 w-3/5" />
            </div>
        )
    }

    if (accessDeniedToFeatureFlag) {
        return <AccessDenied object="feature flag" />
    }

    const earlyAccessFeature = earlyAccessFeaturesList?.find((f: any) => f.flagKey === featureFlag.key)

    const tabs = [
        {
            label: 'Overview',
            key: FeatureFlagsTab.OVERVIEW,
            content: (
                <>
                    <div className="flex flex-col gap-4">
                        <FeatureFlagRollout readOnly />
                        {!featureFlag.is_remote_configuration && (
                            <>
                                <SceneDivider />
                                {/* TODO: In a follow up, clean up super_groups and combine into regular ReleaseConditions component */}
                                {featureFlag.filters.super_groups && featureFlag.filters.super_groups.length > 0 && (
                                    <FeatureFlagReleaseConditions readOnly isSuper filters={featureFlag.filters} />
                                )}

                                <FeatureFlagReleaseConditions readOnly filters={featureFlag.filters} />

                                <SceneDivider />

                                <SceneSection title="Insights that use this feature flag">
                                    <RecentFeatureFlagInsights />
                                </SceneSection>

                                {featureFlags[FEATURE_FLAGS.AUTO_ROLLBACK_FEATURE_FLAGS] && (
                                    <FeatureFlagAutoRollback readOnly />
                                )}
                            </>
                        )}

                        {newSceneLayout ? <SceneDivider /> : <LemonDivider className="my-0" />}
                        <FeatureFlagCodeExample featureFlag={featureFlag} />
                    </div>
                </>
            ),
        },
    ] as LemonTab<FeatureFlagsTab>[]

    if (featureFlag.key && id) {
        tabs.push({
            label: 'Usage',
            key: FeatureFlagsTab.USAGE,
            content: <UsageTab featureFlag={featureFlag} />,
        })

        tabs.push({
            label: 'Projects',
            key: FeatureFlagsTab.PROJECTS,
            content: <FeatureFlagProjects />,
        })

        tabs.push({
            label: 'Schedule',
            key: FeatureFlagsTab.SCHEDULE,
            content: <FeatureFlagSchedule />,
        })
    }

    if (featureFlags[FEATURE_FLAGS.FF_DASHBOARD_TEMPLATES] && featureFlag.key && id) {
        tabs.push({
            label: (
                <div className="flex flex-row">
                    <div>Analysis</div>
                    <LemonTag className="ml-1 float-right uppercase" type="warning">
                        {' '}
                        Beta
                    </LemonTag>
                </div>
            ),
            key: FeatureFlagsTab.Analysis,
            content: (
                <PostHogFeature flag={FEATURE_FLAGS.FF_DASHBOARD_TEMPLATES} match={true}>
                    <AnalysisTab featureFlag={featureFlag} />
                </PostHogFeature>
            ),
        })
    }

    if (featureFlag.id) {
        tabs.push({
            label: 'History',
            key: FeatureFlagsTab.HISTORY,
            content: <ActivityLog scope={ActivityScope.FEATURE_FLAG} id={featureFlag.id} />,
        })
    }

    if (featureFlag.can_edit) {
        tabs.push({
            label: 'Permissions',
            key: FeatureFlagsTab.PERMISSIONS,
            content: <FeatureFlagPermissions featureFlag={featureFlag} />,
        })
    }

    return (
        <>
            <div className="feature-flag">
                {isNewFeatureFlag || isEditingFlag ? (
                    <Form
                        id="feature-flag"
                        logic={featureFlagLogic}
                        props={props}
                        formKey="featureFlag"
                        enableFormOnSubmit
                        className="deprecated-space-y-4"
                    >
                        <PageHeader
                            buttons={
                                <div className="flex items-center gap-2">
                                    <LemonButton
                                        data-attr="cancel-feature-flag"
                                        type="secondary"
                                        onClick={() => {
                                            if (isEditingFlag) {
                                                editFeatureFlag(false)
                                                loadFeatureFlag()
                                            } else {
                                                router.actions.push(urls.featureFlags())
                                            }
                                        }}
                                    >
                                        Cancel
                                    </LemonButton>
                                    <LemonButton
                                        type="primary"
                                        data-attr="save-feature-flag"
                                        htmlType="submit"
                                        form="feature-flag"
                                    >
                                        Save
                                    </LemonButton>
                                </div>
                            }
                        />
                        <SceneContent forceNewSpacing>
                            {featureFlag.experiment_set && featureFlag.experiment_set.length > 0 && (
                                <LemonBanner type="warning">
                                    This feature flag is linked to an experiment. Edit settings here only for advanced
                                    functionality. If unsure, go back to{' '}
                                    <Link to={urls.experiment(featureFlag.experiment_set[0])}>
                                        the experiment creation screen.
                                    </Link>
                                </LemonBanner>
                            )}
                            <div className="max-w-1/2 deprecated-space-y-4">
                                <LemonField
                                    name="key"
                                    label="Key"
                                    help={
                                        hasKeyChanged && id !== 'new' ? (
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
                                            <span className="text-secondary text-sm">
                                                Feature flag keys must be unique
                                            </span>
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
                                        {({ value, onChange }) => {
                                            return (
                                                <ObjectTags
                                                    saving={featureFlagLoading}
                                                    tags={value}
                                                    onChange={(tags) => onChange(tags)}
                                                    tagsAvailable={tags.filter(
                                                        (tag: string) => !featureFlag.tags?.includes(tag)
                                                    )}
                                                    className="mt-2"
                                                />
                                            )
                                        }}
                                    </LemonField>
                                )}
                                <LemonField name="active">
                                    {({ value, onChange }) => (
                                        <div className="border rounded p-4">
                                            <LemonCheckbox
                                                id="flag-enabled-checkbox"
                                                label="Enable feature flag"
                                                onChange={() => onChange(!value)}
                                                checked={value}
                                                data-attr="feature-flag-enabled-checkbox"
                                            />
                                        </div>
                                    )}
                                </LemonField>
                                {!featureFlag.is_remote_configuration && (
                                    <LemonField name="ensure_experience_continuity">
                                        {({ value, onChange }) => (
                                            <div className="border rounded p-4">
                                                <LemonCheckbox
                                                    id="continuity-checkbox"
                                                    label="Persist flag across authentication steps"
                                                    onChange={() => onChange(!value)}
                                                    fullWidth
                                                    checked={value}
                                                />
                                                <div className="text-secondary text-sm pl-7">
                                                    If your feature flag is applied before identifying the user, use
                                                    this to ensure that the flag value remains consistent for the same
                                                    user. Depending on your setup, this option might not always be
                                                    suitable. This feature requires creating profiles for anonymous
                                                    users.{' '}
                                                    <Link
                                                        to="https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps"
                                                        target="_blank"
                                                    >
                                                        Learn more
                                                    </Link>
                                                </div>
                                            </div>
                                        )}
                                    </LemonField>
                                )}
                            </div>
                            {newSceneLayout ? <SceneDivider /> : <LemonDivider className="my-2" />}
                            <FeatureFlagRollout />
                            {newSceneLayout ? <SceneDivider /> : <LemonDivider className="my-2" />}
                            {!featureFlag.is_remote_configuration && (
                                <>
                                    <FeatureFlagReleaseConditions
                                        id={`${featureFlag.id}`}
                                        filters={featureFlag.filters}
                                        onChange={setFeatureFlagFilters}
                                    />
                                    {newSceneLayout ? <SceneDivider /> : <LemonDivider className="my-2" />}
                                </>
                            )}

                            <FeatureFlagCodeExample featureFlag={featureFlag} />
                            <LemonDivider />
                            {isNewFeatureFlag && (
                                <>
                                    <div>
                                        <LemonButton
                                            fullWidth
                                            onClick={() => setAdvancedSettingsExpanded(!advancedSettingsExpanded)}
                                            sideIcon={advancedSettingsExpanded ? <IconCollapse /> : <IconExpand />}
                                        >
                                            <div>
                                                <h3 className="l4 mt-2">Advanced settings</h3>
                                                <div className="text-secondary mb-2 font-medium">
                                                    Define who can modify this flag.
                                                </div>
                                            </div>
                                        </LemonButton>
                                    </div>
                                    {advancedSettingsExpanded && (
                                        <>
                                            {featureFlags[FEATURE_FLAGS.AUTO_ROLLBACK_FEATURE_FLAGS] && (
                                                <FeatureFlagAutoRollback />
                                            )}
                                            <div className="border rounded bg-surface-primary">
                                                <h3 className="p-2 mb-0">Permissions</h3>
                                                <LemonDivider className="my-0" />
                                                <div className="p-3">
                                                    <FeatureFlagPermissions featureFlag={featureFlag} />
                                                </div>
                                            </div>
                                        </>
                                    )}
                                    <LemonDivider />
                                </>
                            )}
                            <div className="flex items-center gap-2 justify-end">
                                <LemonButton
                                    data-attr="cancel-feature-flag"
                                    type="secondary"
                                    onClick={() => {
                                        if (isEditingFlag) {
                                            editFeatureFlag(false)
                                            loadFeatureFlag()
                                        } else {
                                            router.actions.push(urls.featureFlags())
                                        }
                                    }}
                                >
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    data-attr="save-feature-flag"
                                    htmlType="submit"
                                    form="feature-flag"
                                >
                                    Save
                                </LemonButton>
                            </div>
                        </SceneContent>
                    </Form>
                ) : (
                    <>
                        <PageHeader
                            notebookProps={{
                                href: urls.featureFlag(id),
                            }}
                            caption={
                                !newSceneLayout && (
                                    <div>
                                        <div className="flex flex-wrap items-center gap-2">
                                            <div className="flex deprecated-space-x-1">
                                                <div>
                                                    <span className="text-secondary">Key:</span>{' '}
                                                    <CopyToClipboardInline
                                                        tooltipMessage={null}
                                                        description="Feature flag key"
                                                        className="justify-end"
                                                    >
                                                        {featureFlag.key}
                                                    </CopyToClipboardInline>
                                                </div>
                                            </div>
                                            <div>
                                                {featureFlag?.tags && (
                                                    <>
                                                        {featureFlag.tags.length > 0 ? (
                                                            <span className="text-secondary">Tags:</span>
                                                        ) : null}{' '}
                                                        {featureFlag.can_edit ? (
                                                            <ObjectTags
                                                                tags={featureFlag.tags}
                                                                onChange={(tags) => {
                                                                    saveFeatureFlag({ tags })
                                                                }}
                                                                tagsAvailable={tags.filter(
                                                                    (tag: string) => !featureFlag.tags?.includes(tag)
                                                                )}
                                                            />
                                                        ) : featureFlag.tags.length > 0 ? (
                                                            <ObjectTags tags={featureFlag.tags} staticOnly />
                                                        ) : null}
                                                    </>
                                                )}
                                            </div>
                                        </div>
                                        <div className="mt-2">{featureFlag.name || <i>Description (optional)</i>}</div>
                                    </div>
                                )
                            }
                            buttons={
                                <>
                                    <div className="flex items-center gap-2">
                                        <More
                                            loading={newCohortLoading}
                                            overlay={
                                                <>
                                                    {featureFlags[FEATURE_FLAGS.FEATURE_FLAG_COHORT_CREATION] && (
                                                        <>
                                                            <LemonButton
                                                                loading={newCohortLoading}
                                                                onClick={() => {
                                                                    createStaticCohort()
                                                                }}
                                                                fullWidth
                                                            >
                                                                Create Cohort
                                                            </LemonButton>
                                                            <LemonDivider />
                                                        </>
                                                    )}

                                                    <LemonButton
                                                        to={urls.featureFlagDuplicate(featureFlag.id)}
                                                        fullWidth
                                                    >
                                                        <span>Duplicate feature flag</span>
                                                    </LemonButton>

                                                    {openMax && (
                                                        <LemonButton
                                                            data-attr="create-survey"
                                                            fullWidth
                                                            onClick={openMax}
                                                        >
                                                            Create survey
                                                        </LemonButton>
                                                    )}
                                                    <LemonDivider />
                                                    <AccessControlledLemonButton
                                                        userAccessLevel={featureFlag.user_access_level}
                                                        minAccessLevel={AccessControlLevel.Editor}
                                                        resourceType={AccessControlResourceType.FeatureFlag}
                                                        data-attr={
                                                            featureFlag.deleted
                                                                ? 'restore-feature-flag'
                                                                : 'delete-feature-flag'
                                                        }
                                                        status="danger"
                                                        fullWidth
                                                        onClick={() => {
                                                            featureFlag.deleted
                                                                ? restoreFeatureFlag(featureFlag)
                                                                : deleteFeatureFlag(featureFlag)
                                                        }}
                                                        disabledReason={
                                                            !featureFlag.can_edit
                                                                ? "You have only 'View' access for this feature flag. To make changes, please contact the flag's creator."
                                                                : (featureFlag.features?.length || 0) > 0
                                                                  ? 'This feature flag is in use with an early access feature. Delete the early access feature to delete this flag'
                                                                  : (featureFlag.experiment_set?.length || 0) > 0
                                                                    ? 'This feature flag is linked to an experiment. Delete the experiment to delete this flag'
                                                                    : (featureFlag.surveys?.length || 0) > 0
                                                                      ? 'This feature flag is linked to a survey. Delete the survey to delete this flag'
                                                                      : null
                                                        }
                                                    >
                                                        {featureFlag.deleted ? 'Restore' : 'Delete'} feature flag
                                                    </AccessControlledLemonButton>
                                                </>
                                            }
                                        />

                                        <LemonDivider vertical />

                                        <NotebookSelectButton
                                            resource={{
                                                type: NotebookNodeType.FeatureFlag,
                                                attrs: { id: featureFlag.id },
                                            }}
                                            type="secondary"
                                        />

                                        <AccessControlledLemonButton
                                            userAccessLevel={featureFlag.user_access_level}
                                            minAccessLevel={AccessControlLevel.Editor}
                                            resourceType={AccessControlResourceType.FeatureFlag}
                                            data-attr="edit-feature-flag"
                                            type="secondary"
                                            disabledReason={
                                                !featureFlag.can_edit
                                                    ? "You have only 'View' access for this feature flag. To make changes, please contact the flag's creator."
                                                    : featureFlag.deleted
                                                      ? 'This feature flag has been deleted. Restore it to edit.'
                                                      : null
                                            }
                                            onClick={() => {
                                                editFeatureFlag(true)
                                            }}
                                        >
                                            Edit
                                        </AccessControlledLemonButton>
                                    </div>
                                </>
                            }
                        />
                        <SceneContent forceNewSpacing>
                            {earlyAccessFeature && earlyAccessFeature.stage === EarlyAccessFeatureStage.Concept && (
                                <LemonBanner type="info">
                                    This feature flag is assigned to an early access feature in the{' '}
                                    <LemonTag type="default" className="uppercase">
                                        Concept
                                    </LemonTag>{' '}
                                    stage. All users who register interest will be assigned this feature flag. Gate your
                                    code behind a different feature flag if you'd like to keep it hidden, and then
                                    switch your code to this feature flag when you're ready to release to your early
                                    access users.
                                </LemonBanner>
                            )}
                            <SceneTitleSection
                                name={featureFlag.key}
                                description={featureFlag.name}
                                resourceType={{
                                    type: 'feature_flag',
                                }}
                            />
                            <SceneDivider />
                            <LemonTabs
                                activeKey={activeTab}
                                onChange={(tab) => tab !== activeTab && setActiveTab(tab)}
                                tabs={tabs}
                                sceneInset={newSceneLayout}
                            />
                        </SceneContent>
                    </>
                )}
            </div>
        </>
    )
}

function UsageTab({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    const {
        key: featureFlagKey,
        usage_dashboard: dashboardId,
        has_enriched_analytics: hasEnrichedAnalytics,
    } = featureFlag
    const { generateUsageDashboard, enrichUsageDashboard } = useActions(featureFlagLogic)
    const { featureFlagLoading } = useValues(featureFlagLogic)
    let dashboard: DashboardType<QueryBasedInsightModel> | null = null
    if (dashboardId) {
        // FIXME: Refactor out into <ConnectedDashboard />, as React hooks under conditional branches are no good
        // eslint-disable-next-line react-hooks/rules-of-hooks
        const dashboardLogicValues = useValues(
            dashboardLogic({ id: dashboardId, placement: DashboardPlacement.FeatureFlag })
        )
        dashboard = dashboardLogicValues.dashboard
    }

    const { closeEnrichAnalyticsNotice } = useActions(featureFlagsLogic)
    const { enrichAnalyticsNoticeAcknowledged } = useValues(featureFlagsLogic)

    useEffect(() => {
        if (
            dashboard &&
            hasEnrichedAnalytics &&
            !(dashboard.tiles?.find((tile) => (tile.insight?.name?.indexOf('Feature Viewed') ?? -1) > -1) !== undefined)
        ) {
            enrichUsageDashboard()
        }
    }, [dashboard, hasEnrichedAnalytics, enrichUsageDashboard])

    const propertyFilter: AnyPropertyFilter[] = [
        {
            key: '$feature_flag',
            type: PropertyFilterType.Event,
            value: featureFlagKey,
            operator: PropertyOperator.Exact,
        },
    ]

    if (featureFlag.deleted) {
        return (
            <div data-attr="feature-flag-usage-deleted-banner">
                <LemonBanner type="error">This feature flag has been deleted.</LemonBanner>
            </div>
        )
    }

    return (
        <div data-attr="feature-flag-usage-container">
            {dashboard ? (
                <>
                    {!hasEnrichedAnalytics && !enrichAnalyticsNoticeAcknowledged && (
                        <LemonBanner type="info" className="mb-3" onClose={() => closeEnrichAnalyticsNotice()}>
                            Get richer insights automatically by{' '}
                            <Link
                                to="https://posthog.com/docs/libraries/js/features#enriched-flag-analytics"
                                target="_blank"
                            >
                                enabling enriched analytics for flags{' '}
                            </Link>
                        </LemonBanner>
                    )}
                    <Dashboard id={dashboardId!.toString()} placement={DashboardPlacement.FeatureFlag} />
                </>
            ) : (
                <div>
                    <b>Dashboard</b>
                    <div className="text-secondary mb-2">
                        There is currently no connected dashboard to this feature flag. If there was previously a
                        connected dashboard, it may have been deleted.
                    </div>
                    {featureFlagLoading ? (
                        <EmptyDashboardComponent loading={true} canEdit={false} />
                    ) : (
                        <LemonButton type="primary" onClick={() => generateUsageDashboard()}>
                            Generate Usage Dashboard
                        </LemonButton>
                    )}
                </div>
            )}
            <div className="mt-4 mb-4">
                <b>Log</b>
                <div className="text-secondary">{`Feature flag calls for "${featureFlagKey}" will appear here`}</div>
            </div>
            <Query
                query={{
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.EventsQuery,
                        select: [...defaultDataTableColumns(NodeKind.EventsQuery), 'properties.$feature_flag_response'],
                        event: '$feature_flag_called',
                        properties: propertyFilter,
                        after: '-30d',
                    },
                    full: false,
                    showDateRange: true,
                }}
            />
        </div>
    )
}

function variantConcatWithPunctuation(phrases: string[]): string {
    if (phrases === null || phrases.length < 3) {
        return concatWithPunctuation(phrases)
    }
    return `${phrases[0]} and ${phrases.length - 1} more sets`
}

function FeatureFlagRollout({ readOnly }: { readOnly?: boolean }): JSX.Element {
    const {
        multivariateEnabled,
        variants,
        areVariantRolloutsValid,
        variantRolloutSum,
        nonEmptyVariants,
        aggregationTargetName,
        featureFlag,
        recordingFilterForFlag,
        flagStatus,
        flagType,
        flagTypeString,
        hasEncryptedPayloadBeenSaved,
        hasExperiment,
        isDraftExperiment,
    } = useValues(featureFlagLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const {
        distributeVariantsEqually,
        addVariant,
        removeVariant,
        setMultivariateEnabled,
        setFeatureFlag,
        saveFeatureFlag,
        setRemoteConfigEnabled,
        resetEncryptedPayload,
    } = useActions(featureFlagLogic)
    const { addProductIntentForCrossSell } = useActions(teamLogic)

    const filterGroups: FeatureFlagGroupType[] = featureFlag.filters.groups || []

    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

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

    const confirmEncryptedPayloadReset = (): void => {
        LemonDialog.open({
            title: 'Reset payload?',
            description: 'The existing payload will not be reset until the feature flag is saved.',
            primaryButton: {
                children: 'Reset',
                onClick: resetEncryptedPayload,
                size: 'small',
                status: 'danger',
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            },
        })
    }

    const reportViewRecordingsClicked = (variantKey?: string): void => {
        const properties: Record<string, string> = {
            multivariate: multivariateEnabled.toString(),
        }
        if (variantKey) {
            properties.variant_key = variantKey
        }
        posthog.capture('viewed recordings from feature flag', properties)
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
        <SceneContent forceNewSpacing>
            {readOnly ? (
                <>
                    <div className="flex flex-col">
                        <div className="grid grid-cols-8">
                            <div className="col-span-2 card-secondary">Status</div>
                            <div className="col-span-6 card-secondary">Type</div>
                            <div className="col-span-2">
                                {featureFlag.deleted ? (
                                    <LemonTag size="medium" type="danger" className="uppercase">
                                        Deleted
                                    </LemonTag>
                                ) : (
                                    <div className="flex gap-2">
                                        <AccessControlAction
                                            userAccessLevel={featureFlag.user_access_level}
                                            minAccessLevel={AccessControlLevel.Editor}
                                            resourceType={AccessControlResourceType.FeatureFlag}
                                        >
                                            {({ disabledReason: accessControlDisabledReason }) => (
                                                <>
                                                    <LemonSwitch
                                                        onChange={(newValue) => {
                                                            LemonDialog.open({
                                                                title: `${
                                                                    newValue === true ? 'Enable' : 'Disable'
                                                                } this flag?`,
                                                                description: `This flag will be immediately ${
                                                                    newValue === true
                                                                        ? 'rolled out to'
                                                                        : 'rolled back from'
                                                                } the users matching the release conditions.`,
                                                                primaryButton: {
                                                                    children: 'Confirm',
                                                                    type: 'primary',
                                                                    onClick: () => {
                                                                        const updatedFlag = {
                                                                            ...featureFlag,
                                                                            active: newValue,
                                                                        }
                                                                        setFeatureFlag(updatedFlag)
                                                                        saveFeatureFlag(updatedFlag)
                                                                    },
                                                                    size: 'small',
                                                                },
                                                                secondaryButton: {
                                                                    children: 'Cancel',
                                                                    type: 'tertiary',
                                                                    size: 'small',
                                                                },
                                                            })
                                                        }}
                                                        label={featureFlag.active ? 'Enabled' : 'Disabled'}
                                                        disabledReason={
                                                            accessControlDisabledReason ||
                                                            (!featureFlag.can_edit
                                                                ? "You only have view access to this feature flag. To make changes, contact the flag's creator."
                                                                : null)
                                                        }
                                                        checked={featureFlag.active}
                                                    />
                                                    {!featureFlag.is_remote_configuration && (
                                                        <FeatureFlagStatusIndicator flagStatus={flagStatus} />
                                                    )}
                                                </>
                                            )}
                                        </AccessControlAction>
                                    </div>
                                )}
                            </div>
                            <div className="col-span-6">
                                <span className="mt-1">{flagTypeString}</span>
                            </div>
                        </div>

                        <span className="card-secondary mt-4">Flag persistence</span>
                        <span>
                            This flag{' '}
                            <b>{featureFlag.ensure_experience_continuity ? 'persists' : 'does not persist'} </b>
                            across authentication events.
                        </span>

                        {featureFlags[FEATURE_FLAGS.FLAG_EVALUATION_RUNTIMES] && (
                            <>
                                <span className="card-secondary mt-4">Evaluation runtime</span>
                                <div className="mt-2">
                                    <div className="flex items-center gap-2">
                                        {featureFlag.evaluation_runtime === FeatureFlagEvaluationRuntime.ALL ? (
                                            <>
                                                <IconGlobe className="text-lg text-muted" />
                                                <span className="font-medium">Both client and server</span>
                                                <LemonTag type="primary" size="small">
                                                    Single + multi-user
                                                </LemonTag>
                                            </>
                                        ) : featureFlag.evaluation_runtime === FeatureFlagEvaluationRuntime.CLIENT ? (
                                            <>
                                                <IconLaptop className="text-lg text-muted" />
                                                <span className="font-medium">Client-side only</span>
                                                <LemonTag type="completion" size="small">
                                                    Single-user apps
                                                </LemonTag>
                                            </>
                                        ) : (
                                            <>
                                                <IconServer className="text-lg text-muted" />
                                                <span className="font-medium">Server-side only</span>
                                                <LemonTag type="caution" size="small">
                                                    Multi-user systems
                                                </LemonTag>
                                            </>
                                        )}
                                    </div>
                                </div>
                            </>
                        )}
                    </div>
                    {newSceneLayout ? <SceneDivider /> : <LemonDivider className="my-0" />}
                    {featureFlag.filters.multivariate && (
                        <>
                            <SceneSection title="Variant keys">
                                <div className="border rounded p-4 bg-surface-primary">
                                    <div className="grid grid-cols-10 gap-4 font-semibold">
                                        <div className="col-span-2">Key</div>
                                        <div className="col-span-2">Description</div>
                                        <div className="col-span-2">Payload</div>
                                        <div>Rollout</div>
                                    </div>
                                    <LemonDivider className="my-3" />
                                    {variants.map((variant: MultivariateFlagVariant, index: number) => (
                                        <div key={index}>
                                            <div className="grid grid-cols-10 gap-4">
                                                <div className="col-span-2">
                                                    <Lettermark name={alphabet[index]} color={LettermarkColor.Gray} />
                                                    <CopyToClipboardInline
                                                        tooltipMessage={null}
                                                        description="key"
                                                        style={{
                                                            marginLeft: '0.5rem',
                                                        }}
                                                        iconStyle={{ color: 'var(--color-text-secondary)' }}
                                                    >
                                                        {variant.key}
                                                    </CopyToClipboardInline>
                                                </div>
                                                <div className="col-span-2">
                                                    <span className={variant.name ? '' : 'text-muted'}>
                                                        {variant.name || 'There is no description for this variant key'}
                                                    </span>
                                                </div>
                                                <div className="col-span-2">
                                                    {featureFlag.filters.payloads?.[index] ? (
                                                        <JSONEditorInput
                                                            readOnly={true}
                                                            value={featureFlag.filters.payloads[index]}
                                                        />
                                                    ) : (
                                                        <span className="text-secondary">
                                                            No payload associated with this variant
                                                        </span>
                                                    )}
                                                </div>
                                                <div>{variant.rollout_percentage}%</div>
                                                <div className="col-span-2">
                                                    <LemonButton
                                                        size="xsmall"
                                                        icon={<IconRewindPlay />}
                                                        type="secondary"
                                                        onClick={() => {
                                                            reportViewRecordingsClicked(variant.key)
                                                            router.actions.push(
                                                                urls.replay(
                                                                    ReplayTabs.Home,
                                                                    getRecordingFilterForFlagVariant(
                                                                        featureFlag.key,
                                                                        variant.key,
                                                                        featureFlag.has_enriched_analytics
                                                                    )
                                                                )
                                                            )
                                                            addProductIntentForCrossSell({
                                                                from: ProductKey.FEATURE_FLAGS,
                                                                to: ProductKey.SESSION_REPLAY,
                                                                intent_context:
                                                                    ProductIntentContext.FEATURE_FLAG_VIEW_RECORDINGS,
                                                            })
                                                        }}
                                                    >
                                                        View recordings
                                                    </LemonButton>
                                                </div>
                                            </div>
                                            {index !== variants.length - 1 && <LemonDivider className="my-3" />}
                                        </div>
                                    ))}
                                </div>
                            </SceneSection>
                        </>
                    )}
                </>
            ) : (
                <>
                    {featureFlags[FEATURE_FLAGS.FLAG_EVALUATION_RUNTIMES] && (
                        <>
                            <SceneSection
                                title={
                                    <span className="flex items-center gap-2">
                                        Evaluation runtime
                                        <Tooltip title="This setting controls where your feature flag can be evaluated. If you try to use a flag in a runtime where it's not allowed (e.g., using a server-only flag in client-side code), it won't evaluate.">
                                            <IconInfo className="text-secondary text-lg" />
                                        </Tooltip>
                                    </span>
                                }
                            >
                                <LemonField name="evaluation_runtime">
                                    {({ value, onChange }) => (
                                        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                                            {[
                                                {
                                                    value: FeatureFlagEvaluationRuntime.ALL,
                                                    icon: <IconGlobe />,
                                                    title: 'Both client and server',
                                                    description: 'Single-user apps + multi-user systems',
                                                },
                                                {
                                                    value: FeatureFlagEvaluationRuntime.CLIENT,
                                                    icon: <IconLaptop />,
                                                    title: 'Client-side only',
                                                    description: 'Single-user apps (mobile, desktop, embedded)',
                                                },
                                                {
                                                    value: FeatureFlagEvaluationRuntime.SERVER,
                                                    icon: <IconServer />,
                                                    title: 'Server-side only',
                                                    description: 'Multi-user systems in trusted environments',
                                                },
                                            ].map((option) => (
                                                <div
                                                    key={option.value}
                                                    className={`border rounded-lg p-4 cursor-pointer transition-all hover:border-primary-light ${
                                                        value === option.value
                                                            ? 'border-primary bg-primary-highlight'
                                                            : 'border-border'
                                                    }`}
                                                    onClick={() => onChange(option.value)}
                                                >
                                                    <div className="flex items-start gap-3">
                                                        <div className="text-lg text-muted">{option.icon}</div>
                                                        <div className="flex-1">
                                                            <div className="font-medium text-sm">{option.title}</div>
                                                            <div className="text-xs text-muted mt-1">
                                                                {option.description}
                                                            </div>
                                                        </div>
                                                        <input
                                                            type="radio"
                                                            name="evaluation-environment"
                                                            checked={value === option.value}
                                                            onChange={() => onChange(option.value)}
                                                            className="cursor-pointer"
                                                        />
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </LemonField>
                            </SceneSection>

                            <SceneDivider />
                        </>
                    )}

                    <SceneSection title="Served value">
                        <div data-attr="feature-flag-served-value-segmented-button">
                            <LemonSegmentedButton
                                size="small"
                                options={[
                                    {
                                        label: 'Release toggle (boolean)',
                                        value: 'boolean',
                                        disabledReason: hasExperiment
                                            ? 'This feature flag is associated with an experiment.'
                                            : undefined,
                                    },
                                    {
                                        label: <span>Multiple variants with rollout percentages (A/B/n test)</span>,
                                        value: 'multivariate',
                                    },
                                    {
                                        label: <span>Remote config (single payload)</span>,
                                        value: 'remote_config',
                                        disabledReason: hasExperiment
                                            ? 'This feature flag is associated with an experiment.'
                                            : undefined,
                                    },
                                ]}
                                onChange={(value) => {
                                    if (['boolean', 'remote_config'].includes(value) && nonEmptyVariants.length) {
                                        confirmRevertMultivariateEnabled()
                                    } else {
                                        setMultivariateEnabled(value === 'multivariate')
                                        setRemoteConfigEnabled(value === 'remote_config')
                                        focusVariantKeyField(0)
                                    }
                                }}
                                value={flagType}
                            />
                        </div>
                        <div className="text-secondary">
                            {featureFlag.is_remote_configuration ? (
                                <span>
                                    Remote config flags provide runtime configuration values in your app. Read more in
                                    the{' '}
                                    <Link to="https://posthog.com/docs/feature-flags/remote-config">
                                        remote config flags documentation
                                    </Link>
                                    .
                                </span>
                            ) : (
                                <>
                                    {capitalizeFirstLetter(aggregationTargetName)} will be served{' '}
                                    {multivariateEnabled ? (
                                        <>
                                            <strong>a variant key</strong> according to the below distribution
                                        </>
                                    ) : (
                                        <strong>
                                            <code>true</code>
                                        </strong>
                                    )}{' '}
                                    <span>if they match one or more release condition groups.</span>
                                </>
                            )}
                        </div>
                    </SceneSection>
                    {!multivariateEnabled && (
                        <>
                            <SceneDivider />
                            <SceneSection title="Payload">
                                {readOnly ? (
                                    featureFlag.filters.payloads?.['true'] ? (
                                        <JSONEditorInput
                                            readOnly={readOnly}
                                            value={featureFlag.filters.payloads?.['true']}
                                        />
                                    ) : (
                                        <span className="text-secondary">No payload associated with this flag</span>
                                    )
                                ) : (
                                    <div className="w-1/2">
                                        <div className="text-secondary mb-4">
                                            {featureFlag.is_remote_configuration ? (
                                                <>
                                                    Specify a valid JSON payload to be returned for the config flag.
                                                    Read more in the{' '}
                                                    <Link to="https://posthog.com/docs/feature-flags/creating-feature-flags#payloads">
                                                        payload documentation
                                                    </Link>
                                                    .
                                                </>
                                            ) : (
                                                <>
                                                    Optionally specify a valid JSON payload to be returned when the
                                                    served value is{' '}
                                                    <strong>
                                                        <code>true</code>
                                                    </strong>
                                                    . Read more in the{' '}
                                                    <Link to="https://posthog.com/docs/feature-flags/creating-feature-flags#payloads">
                                                        payload documentation
                                                    </Link>
                                                    .
                                                </>
                                            )}
                                        </div>
                                        {featureFlag.is_remote_configuration && (
                                            <LemonField name="has_encrypted_payloads">
                                                {({ value, onChange }) => (
                                                    <div className="border rounded mb-4 p-4">
                                                        <LemonCheckbox
                                                            id="flag-payload-encrypted-checkbox"
                                                            label="Encrypt remote configuration payload"
                                                            onChange={() => onChange(!value)}
                                                            checked={value}
                                                            data-attr="feature-flag-payload-encrypted-checkbox"
                                                            disabledReason={
                                                                hasEncryptedPayloadBeenSaved &&
                                                                'An encrypted payload has already been saved for this flag. Reset the payload or create a new flag to create an unencrypted configuration payload.'
                                                            }
                                                        />
                                                    </div>
                                                )}
                                            </LemonField>
                                        )}
                                        <div className="flex gap-2">
                                            <Group name={['filters', 'payloads']}>
                                                <LemonField name="true" className="grow">
                                                    <JSONEditorInput
                                                        readOnly={
                                                            readOnly ||
                                                            (featureFlag.has_encrypted_payloads &&
                                                                Boolean(featureFlag.filters?.payloads?.['true']))
                                                        }
                                                        placeholder={'Examples: "A string", 2500, {"key": "value"}'}
                                                    />
                                                </LemonField>
                                            </Group>
                                            {featureFlag.has_encrypted_payloads && (
                                                <LemonButton
                                                    className="grow-0"
                                                    icon={<IconTrash />}
                                                    type="secondary"
                                                    size="small"
                                                    status="danger"
                                                    onClick={confirmEncryptedPayloadReset}
                                                >
                                                    Reset
                                                </LemonButton>
                                            )}
                                        </div>
                                        {featureFlag.is_remote_configuration && (
                                            <div className="text-sm text-secondary mt-4">
                                                Note: remote config flags must be accessed through payloads, e.g.{' '}
                                                <span className="font-mono font-bold">
                                                    {featureFlag.has_encrypted_payloads
                                                        ? 'getRemoteConfigPayload'
                                                        : 'getFeatureFlagPayload'}
                                                </span>
                                                . Using standard SDK methods such as{' '}
                                                <span className="font-mono font-bold">getFeatureFlag</span> or{' '}
                                                <span className="font-mono font-bold">isFeatureEnabled</span> will
                                                always return <span className="font-mono font-bold">true</span>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </SceneSection>

                            {readOnly && !featureFlag.is_remote_configuration && (
                                <SceneSection
                                    title="Recordings"
                                    description="Watch recordings of people who have been exposed to the feature flag."
                                >
                                    <div className="inline-block">
                                        <LemonButton
                                            onClick={() => {
                                                reportViewRecordingsClicked()
                                                router.actions.push(
                                                    urls.replay(ReplayTabs.Home, recordingFilterForFlag)
                                                )
                                                addProductIntentForCrossSell({
                                                    from: ProductKey.FEATURE_FLAGS,
                                                    to: ProductKey.SESSION_REPLAY,
                                                    intent_context: ProductIntentContext.FEATURE_FLAG_VIEW_RECORDINGS,
                                                })
                                            }}
                                            icon={<IconRewindPlay />}
                                            type="secondary"
                                            size="small"
                                        >
                                            View recordings
                                        </LemonButton>
                                    </div>
                                </SceneSection>
                            )}
                        </>
                    )}
                    {!readOnly && multivariateEnabled && (
                        <>
                            <LemonDivider className="my-0" />
                            <SceneSection
                                title="Variant keys"
                                description="The rollout percentage of feature flag variants must add up to 100%"
                            >
                                <div className="VariantFormList deprecated-space-y-2 mt-0">
                                    <div className="VariantFormList__row grid label-row gap-2 items-center">
                                        <div />
                                        <div className="col-span-4">Variant key</div>
                                        <div className="col-span-6">Description</div>
                                        <div className="col-span-8">
                                            <div className="flex flex-col">
                                                <b>Payload</b>
                                                <span className="text-secondary font-normal">
                                                    Specify return payload when the variant key matches
                                                </span>
                                            </div>
                                        </div>
                                        <div className="col-span-3 flex justify-between items-center gap-1">
                                            <span>Rollout</span>
                                            <LemonButton
                                                onClick={distributeVariantsEqually}
                                                tooltip="Normalize variant rollout percentages"
                                            >
                                                <IconBalance />
                                            </LemonButton>
                                        </div>
                                    </div>
                                    {variants.map((variant: MultivariateFlagVariant, index: number) => (
                                        <Group key={index} name="filters">
                                            <div className="VariantFormList__row grid gap-2">
                                                <div className="flex items-center justify-center">
                                                    <Lettermark name={alphabet[index]} color={LettermarkColor.Gray} />
                                                </div>
                                                <div className="col-span-4">
                                                    <LemonField name={['multivariate', 'variants', index, 'key']}>
                                                        <LemonInput
                                                            data-attr="feature-flag-variant-key"
                                                            data-key-index={index.toString()}
                                                            className="ph-ignore-input"
                                                            placeholder={`example-variant-${index + 1}`}
                                                            autoComplete="off"
                                                            autoCapitalize="off"
                                                            autoCorrect="off"
                                                            spellCheck={false}
                                                            disabled={!canEditVariant(index)}
                                                        />
                                                    </LemonField>
                                                </div>
                                                <div className="col-span-6">
                                                    <LemonField name={['multivariate', 'variants', index, 'name']}>
                                                        <LemonInput
                                                            data-attr="feature-flag-variant-name"
                                                            className="ph-ignore-input"
                                                            placeholder="Description"
                                                        />
                                                    </LemonField>
                                                </div>
                                                <div className="col-span-8">
                                                    <LemonField name={['payloads', index]}>
                                                        {({ value, onChange }) => {
                                                            return (
                                                                <JSONEditorInput
                                                                    onChange={(newValue) => {
                                                                        onChange(newValue === '' ? undefined : newValue)
                                                                    }}
                                                                    value={value}
                                                                    placeholder='{"key": "value"}'
                                                                />
                                                            )
                                                        }}
                                                    </LemonField>
                                                </div>
                                                <div className="col-span-3">
                                                    <LemonField
                                                        name={['multivariate', 'variants', index, 'rollout_percentage']}
                                                    >
                                                        {({ value, onChange }) => (
                                                            <div>
                                                                <LemonInput
                                                                    type="number"
                                                                    min={0}
                                                                    max={100}
                                                                    // .toString() prevents user from typing leading zeroes
                                                                    value={value.toString()}
                                                                    onChange={(changedValue) => {
                                                                        const valueInt =
                                                                            changedValue !== undefined &&
                                                                            !isNaN(changedValue)
                                                                                ? parseInt(changedValue.toString())
                                                                                : 0

                                                                        onChange(valueInt)
                                                                    }}
                                                                    suffix={<span>%</span>}
                                                                    data-attr="feature-flag-variant-rollout-percentage-input"
                                                                />
                                                                {filterGroups.filter(
                                                                    (group) => group.variant === variant.key
                                                                ).length > 0 && (
                                                                    <span className="text-secondary text-xs">
                                                                        Overridden by{' '}
                                                                        <strong>
                                                                            {variantConcatWithPunctuation(
                                                                                filterGroups
                                                                                    .filter(
                                                                                        (group) =>
                                                                                            group.variant != null &&
                                                                                            group.variant ===
                                                                                                variant.key
                                                                                    )
                                                                                    .map(
                                                                                        (variant) =>
                                                                                            'Set ' +
                                                                                            (filterGroups.findIndex(
                                                                                                (group) =>
                                                                                                    group === variant
                                                                                            ) +
                                                                                                1)
                                                                                    )
                                                                            )}
                                                                        </strong>
                                                                    </span>
                                                                )}
                                                            </div>
                                                        )}
                                                    </LemonField>
                                                </div>
                                                <div className="flex items-center justify-center">
                                                    {variants.length > 1 && (
                                                        <LemonButton
                                                            icon={<IconTrash />}
                                                            data-attr={`delete-prop-filter-${index}`}
                                                            noPadding
                                                            onClick={() => removeVariant(index)}
                                                            disabledReason={
                                                                !canEditVariant(index)
                                                                    ? isDraftExperiment
                                                                        ? 'Cannot delete the control variant from an experiment.'
                                                                        : 'Cannot delete variants from a feature flag that is part of a launched experiment.'
                                                                    : undefined
                                                            }
                                                            tooltipPlacement="top-end"
                                                        />
                                                    )}
                                                </div>
                                            </div>
                                        </Group>
                                    ))}
                                    {variants.length > 0 && !areVariantRolloutsValid && (
                                        <p className="text-danger">
                                            Percentage rollouts for variants must sum to 100 (currently{' '}
                                            {variantRolloutSum}
                                            ).
                                        </p>
                                    )}
                                    <LemonButton
                                        type="secondary"
                                        onClick={() => {
                                            const newIndex = variants.length
                                            addVariant()
                                            focusVariantKeyField(newIndex)
                                        }}
                                        icon={<IconPlus />}
                                        disabledReason={
                                            hasExperiment && !isDraftExperiment
                                                ? 'Cannot add variants to a feature flag that is part of a launched experiment. To update variants, reset the experiment to draft.'
                                                : undefined
                                        }
                                        tooltipPlacement="top-start"
                                        center
                                    >
                                        Add variant
                                    </LemonButton>
                                </div>
                            </SceneSection>
                        </>
                    )}
                </>
            )}
            {readOnly && !multivariateEnabled && (
                <div className="flex flex-col gap-y-4">
                    <SceneSection title="Payload">
                        {readOnly ? (
                            featureFlag.filters.payloads?.['true'] ? (
                                <JSONEditorInput readOnly={readOnly} value={featureFlag.filters.payloads?.['true']} />
                            ) : (
                                <span className="text-secondary">No payload associated with this flag</span>
                            )
                        ) : (
                            <div className="w-1/2">
                                <div className="text-secondary mb-4">
                                    {featureFlag.is_remote_configuration ? (
                                        <>
                                            Specify a valid JSON payload to be returned for the config flag. Read more
                                            in the{' '}
                                            <Link to="https://posthog.com/docs/feature-flags/creating-feature-flags#payloads">
                                                payload documentation
                                            </Link>
                                            .
                                        </>
                                    ) : (
                                        <>
                                            Optionally specify a valid JSON payload to be returned when the served value
                                            is{' '}
                                            <strong>
                                                <code>true</code>
                                            </strong>
                                            . Read more in the{' '}
                                            <Link to="https://posthog.com/docs/feature-flags/creating-feature-flags#payloads">
                                                payload documentation
                                            </Link>
                                            .
                                        </>
                                    )}
                                </div>
                                {featureFlag.is_remote_configuration && (
                                    <LemonField name="has_encrypted_payloads">
                                        {({ value, onChange }) => (
                                            <div className="border rounded mb-4 p-4">
                                                <LemonCheckbox
                                                    id="flag-payload-encrypted-checkbox"
                                                    label="Encrypt remote configuration payload"
                                                    onChange={() => onChange(!value)}
                                                    checked={value}
                                                    data-attr="feature-flag-payload-encrypted-checkbox"
                                                    disabledReason={
                                                        hasEncryptedPayloadBeenSaved &&
                                                        'An encrypted payload has already been saved for this flag. Reset the payload or create a new flag to create an unencrypted configuration payload.'
                                                    }
                                                />
                                            </div>
                                        )}
                                    </LemonField>
                                )}
                                <div className="flex gap-2">
                                    <Group name={['filters', 'payloads']}>
                                        <LemonField name="true" className="grow">
                                            <JSONEditorInput
                                                readOnly={
                                                    readOnly ||
                                                    (featureFlag.has_encrypted_payloads &&
                                                        Boolean(featureFlag.filters?.payloads?.['true']))
                                                }
                                                placeholder='Examples: "A string", 2500, {"key": "value"}'
                                            />
                                        </LemonField>
                                    </Group>
                                    {featureFlag.has_encrypted_payloads && (
                                        <LemonButton
                                            className="grow-0"
                                            icon={<IconTrash />}
                                            type="secondary"
                                            size="small"
                                            status="danger"
                                            onClick={confirmEncryptedPayloadReset}
                                        >
                                            Reset
                                        </LemonButton>
                                    )}
                                </div>
                                {featureFlag.is_remote_configuration && (
                                    <div className="text-sm text-secondary mt-4">
                                        Note: remote config flags must be accessed through payloads, e.g.{' '}
                                        <span className="font-mono font-bold">
                                            {featureFlag.has_encrypted_payloads
                                                ? 'getRemoteConfigPayload'
                                                : 'getFeatureFlagPayload'}
                                        </span>
                                        . Using standard SDK methods such as{' '}
                                        <span className="font-mono font-bold">getFeatureFlag</span> or{' '}
                                        <span className="font-mono font-bold">isFeatureEnabled</span> will always return{' '}
                                        <span className="font-mono font-bold">true</span>
                                    </div>
                                )}
                            </div>
                        )}
                    </SceneSection>
                    {readOnly && !featureFlag.is_remote_configuration && (
                        <>
                            <SceneDivider />
                            <SceneSection
                                title="Recordings"
                                description="Watch recordings of people who have been exposed to the feature flag."
                            >
                                <LemonButton
                                    onClick={() => {
                                        reportViewRecordingsClicked()
                                        router.actions.push(urls.replay(ReplayTabs.Home, recordingFilterForFlag))
                                        addProductIntentForCrossSell({
                                            from: ProductKey.FEATURE_FLAGS,
                                            to: ProductKey.SESSION_REPLAY,
                                            intent_context: ProductIntentContext.FEATURE_FLAG_VIEW_RECORDINGS,
                                        })
                                    }}
                                    icon={<IconRewindPlay />}
                                    type="secondary"
                                    size="small"
                                    className="w-fit"
                                >
                                    View recordings
                                </LemonButton>
                            </SceneSection>
                        </>
                    )}
                </div>
            )}
        </SceneContent>
    )
}
