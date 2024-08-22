import './FeatureFlag.scss'

import { IconCollapse, IconExpand, IconPlus, IconTrash } from '@posthog/icons'
import { LemonDialog, LemonSegmentedButton, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { router } from 'kea-router'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { NotFound } from 'lib/components/NotFound'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { FEATURE_FLAGS } from 'lib/constants'
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
import { PostHogFeature } from 'posthog-js/react'
import { useEffect, useState } from 'react'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { EmptyDashboardComponent } from 'scenes/dashboard/EmptyDashboardComponent'
import { UTM_TAGS } from 'scenes/feature-flags/FeatureFlagSnippets'
import { JSONEditorInput } from 'scenes/feature-flags/JSONEditorInput'
import { concatWithPunctuation } from 'scenes/insights/utils'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { ResourcePermission } from 'scenes/ResourcePermissionModal'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { tagsModel } from '~/models/tagsModel'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import {
    ActivityScope,
    AnyPropertyFilter,
    AvailableFeature,
    DashboardPlacement,
    DashboardType,
    FeatureFlagGroupType,
    FeatureFlagType,
    NotebookNodeType,
    PropertyFilterType,
    PropertyOperator,
    QueryBasedInsightModel,
    ReplayTabs,
    Resource,
} from '~/types'

import { AnalysisTab } from './FeatureFlagAnalysisTab'
import { FeatureFlagAutoRollback } from './FeatureFlagAutoRollout'
import { FeatureFlagCodeExample } from './FeatureFlagCodeExample'
import { featureFlagLogic } from './featureFlagLogic'
import { featureFlagPermissionsLogic } from './featureFlagPermissionsLogic'
import FeatureFlagProjects from './FeatureFlagProjects'
import { FeatureFlagReleaseConditions } from './FeatureFlagReleaseConditions'
import FeatureFlagSchedule from './FeatureFlagSchedule'
import { featureFlagsLogic, FeatureFlagsTab } from './featureFlagsLogic'
import { RecentFeatureFlagInsights } from './RecentFeatureFlagInsightsCard'

export const scene: SceneExport = {
    component: FeatureFlag,
    logic: featureFlagLogic,
    paramsToProps: ({ params: { id } }): (typeof featureFlagLogic)['props'] => ({
        id: id && id !== 'new' ? parseInt(id) : 'new',
    }),
}

function focusVariantKeyField(index: number): void {
    setTimeout(
        () => document.querySelector<HTMLElement>(`.VariantFormList input[data-key-index="${index}"]`)?.focus(),
        50
    )
}

export function FeatureFlag({ id }: { id?: string } = {}): JSX.Element {
    const {
        props,
        featureFlag,
        featureFlagLoading,
        featureFlagMissing,
        isEditingFlag,
        recordingFilterForFlag,
        newCohortLoading,
        activeTab,
    } = useValues(featureFlagLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const {
        deleteFeatureFlag,
        editFeatureFlag,
        loadFeatureFlag,
        saveFeatureFlag,
        createStaticCohort,
        setFeatureFlagFilters,
        setActiveTab,
    } = useActions(featureFlagLogic)

    const { addableRoles, unfilteredAddableRolesLoading, rolesToAdd, derivedRoles } = useValues(
        featureFlagPermissionsLogic({ flagId: featureFlag.id })
    )
    const { setRolesToAdd, addAssociatedRoles, deleteAssociatedRole } = useActions(
        featureFlagPermissionsLogic({ flagId: featureFlag.id })
    )

    const { tags } = useValues(tagsModel)
    const { hasAvailableFeature } = useValues(userLogic)

    // whether the key for an existing flag is being changed
    const [hasKeyChanged, setHasKeyChanged] = useState(false)

    const [advancedSettingsExpanded, setAdvancedSettingsExpanded] = useState(false)

    const isNewFeatureFlag = id === 'new' || id === undefined

    if (featureFlagMissing) {
        return <NotFound object="feature flag" />
    }
    if (featureFlagLoading) {
        return (
            <div className="space-y-2">
                <LemonSkeleton active className="h-4 w-2/5" />
                <LemonSkeleton active className="h-4 w-full" />
                <LemonSkeleton active className="h-4 w-full" />
                <LemonSkeleton active className="h-4 w-3/5" />
            </div>
        )
    }

    const tabs = [
        {
            label: 'Overview',
            key: FeatureFlagsTab.OVERVIEW,
            content: (
                <>
                    <div className="flex gap-4 flex-wrap">
                        <div className="flex-1">
                            <FeatureFlagRollout readOnly />
                            {/* TODO: In a follow up, clean up super_groups and combine into regular ReleaseConditions component */}
                            {featureFlag.filters.super_groups && (
                                <FeatureFlagReleaseConditions readOnly isSuper filters={featureFlag.filters} />
                            )}
                            <FeatureFlagReleaseConditions readOnly filters={featureFlag.filters} />
                            {featureFlags[FEATURE_FLAGS.AUTO_ROLLBACK_FEATURE_FLAGS] && (
                                <FeatureFlagAutoRollback readOnly />
                            )}
                        </div>
                        <div className="max-w-120 w-full">
                            <RecentFeatureFlagInsights />
                            <div className="my-4" />
                        </div>
                    </div>
                    <LemonDivider className="mb-4" />
                    <FeatureFlagCodeExample featureFlag={featureFlag} />
                </>
            ),
        },
    ] as LemonTab<FeatureFlagsTab>[]

    if (featureFlag.key && id) {
        tabs.push({
            label: 'Usage',
            key: FeatureFlagsTab.USAGE,
            content: <UsageTab id={id} featureFlag={featureFlag} />,
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
                    <AnalysisTab id={id} featureFlag={featureFlag} />
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
            content: (
                <PayGateMini feature={AvailableFeature.ROLE_BASED_ACCESS}>
                    <ResourcePermission
                        resourceType={Resource.FEATURE_FLAGS}
                        onChange={(roleIds) => setRolesToAdd(roleIds)}
                        rolesToAdd={rolesToAdd}
                        addableRoles={addableRoles}
                        addableRolesLoading={unfilteredAddableRolesLoading}
                        onAdd={() => addAssociatedRoles()}
                        roles={derivedRoles}
                        deleteAssociatedRole={(id) => deleteAssociatedRole({ roleId: id })}
                        canEdit={featureFlag.can_edit}
                    />
                </PayGateMini>
            ),
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
                        className="space-y-4"
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
                        {featureFlag.experiment_set && featureFlag.experiment_set?.length > 0 && (
                            <LemonBanner type="warning">
                                This feature flag is linked to an experiment. Edit settings here only for advanced
                                functionality. If unsure, go back to{' '}
                                <Link to={urls.experiment(featureFlag.experiment_set[0])}>
                                    the experiment creation screen.
                                </Link>
                            </LemonBanner>
                        )}
                        <div className="my-4">
                            <div className="max-w-1/2 space-y-4">
                                <LemonField
                                    name="key"
                                    label="Key"
                                    help={
                                        hasKeyChanged && id !== 'new' ? (
                                            <span className="text-warning">
                                                <b>Warning! </b>Changing this key will
                                                <Link
                                                    to={`https://posthog.com/docs/features/feature-flags${UTM_TAGS}#feature-flag-persistence`}
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
                                            <span className="text-muted text-sm">Feature flag keys must be unique</span>
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
                                                        (tag) => !featureFlag.tags?.includes(tag)
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
                                            />
                                        </div>
                                    )}
                                </LemonField>
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
                                            <div className="text-muted text-sm pl-7">
                                                If your feature flag is applied before identifying the user, use this to
                                                ensure that the flag value remains consistent for the same user.
                                                Depending on your setup, this option might not always be suitable.{' '}
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
                            </div>
                        </div>
                        <LemonDivider />
                        <FeatureFlagRollout />
                        <LemonDivider />
                        <FeatureFlagReleaseConditions
                            id={`${featureFlag.id}`}
                            filters={featureFlag.filters}
                            onChange={setFeatureFlagFilters}
                        />
                        <LemonDivider />
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
                                            <div className="text-muted mb-2 font-medium">
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
                                        <div className="border rounded bg-bg-light">
                                            <h3 className="p-2 mb-0">Permissions</h3>
                                            <LemonDivider className="my-0" />
                                            <div className="p-3">
                                                <PayGateMini feature={AvailableFeature.ROLE_BASED_ACCESS}>
                                                    <ResourcePermission
                                                        resourceType={Resource.FEATURE_FLAGS}
                                                        onChange={(roleIds) => setRolesToAdd(roleIds)}
                                                        rolesToAdd={rolesToAdd}
                                                        addableRoles={addableRoles}
                                                        addableRolesLoading={unfilteredAddableRolesLoading}
                                                        onAdd={() => addAssociatedRoles()}
                                                        roles={derivedRoles}
                                                        deleteAssociatedRole={(id) =>
                                                            deleteAssociatedRole({ roleId: id })
                                                        }
                                                        canEdit={featureFlag.can_edit}
                                                    />
                                                </PayGateMini>
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
                    </Form>
                ) : (
                    <>
                        <PageHeader
                            notebookProps={{
                                href: urls.featureFlag(id),
                            }}
                            caption={
                                <div>
                                    <div className="flex flex-wrap items-center gap-2">
                                        <div className="flex space-x-1">
                                            <div>
                                                <span className="text-muted">Key:</span>{' '}
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
                                                        <span className="text-muted">Tags:</span>
                                                    ) : null}{' '}
                                                    {featureFlag.can_edit ? (
                                                        <ObjectTags
                                                            tags={featureFlag.tags}
                                                            onChange={(tags) => {
                                                                saveFeatureFlag({ tags })
                                                            }}
                                                            tagsAvailable={tags.filter(
                                                                (tag) => !featureFlag.tags?.includes(tag)
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
                            }
                            buttons={
                                <>
                                    <div className="flex items-center gap-2">
                                        <More
                                            loading={newCohortLoading}
                                            overlay={
                                                <>
                                                    <LemonButton
                                                        to={urls.replay(ReplayTabs.Recent, recordingFilterForFlag)}
                                                        fullWidth
                                                    >
                                                        View Recordings
                                                    </LemonButton>
                                                    {featureFlags[FEATURE_FLAGS.FEATURE_FLAG_COHORT_CREATION] && (
                                                        <LemonButton
                                                            loading={newCohortLoading}
                                                            onClick={() => {
                                                                createStaticCohort()
                                                            }}
                                                            fullWidth
                                                        >
                                                            Create Cohort
                                                        </LemonButton>
                                                    )}
                                                    <LemonDivider />
                                                    <LemonButton
                                                        data-attr="delete-feature-flag"
                                                        status="danger"
                                                        fullWidth
                                                        onClick={() => {
                                                            deleteFeatureFlag(featureFlag)
                                                        }}
                                                        disabledReason={
                                                            !featureFlag.can_edit
                                                                ? "You have only 'View' access for this feature flag. To make changes, please contact the flag's creator."
                                                                : (featureFlag.features?.length || 0) > 0
                                                                ? 'This feature flag is in use with an early access feature. Delete the early access feature to delete this flag'
                                                                : (featureFlag.experiment_set?.length || 0) > 0
                                                                ? 'This feature flag is linked to an experiment. Delete the experiment to delete this flag'
                                                                : null
                                                        }
                                                    >
                                                        Delete feature flag
                                                    </LemonButton>
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
                                        <LemonButton
                                            data-attr="edit-feature-flag"
                                            type="secondary"
                                            disabledReason={
                                                !featureFlag.can_edit &&
                                                "You have only 'View' access for this feature flag. To make changes, please contact the flag's creator."
                                            }
                                            onClick={() => {
                                                editFeatureFlag(true)
                                            }}
                                        >
                                            Edit
                                        </LemonButton>
                                    </div>
                                </>
                            }
                        />
                        <LemonTabs
                            activeKey={activeTab}
                            onChange={(tab) => tab !== activeTab && setActiveTab(tab)}
                            tabs={tabs}
                        />
                    </>
                )}
            </div>
        </>
    )
}

function UsageTab({ featureFlag }: { id: string; featureFlag: FeatureFlagType }): JSX.Element {
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
    }, [dashboard])

    const propertyFilter: AnyPropertyFilter[] = [
        {
            key: '$feature_flag',
            type: PropertyFilterType.Event,
            value: featureFlagKey,
            operator: PropertyOperator.Exact,
        },
    ]

    return (
        <div>
            {dashboard ? (
                <>
                    {!hasEnrichedAnalytics && !enrichAnalyticsNoticeAcknowledged && (
                        <LemonBanner type="info" className="mb-3" onClose={() => closeEnrichAnalyticsNotice()}>
                            Get richer insights automatically by{' '}
                            <Link to="https://posthog.com/docs/libraries/js#enriched-analytics" target="_blank">
                                enabling enriched analytics for flags{' '}
                            </Link>
                        </LemonBanner>
                    )}
                    <Dashboard id={dashboardId!.toString()} placement={DashboardPlacement.FeatureFlag} />
                </>
            ) : (
                <div>
                    <b>Dashboard</b>
                    <div className="text-muted mb-2">
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
                <div className="text-muted">{`Feature flag calls for "${featureFlagKey}" will appear here`}</div>
            </div>
            <Query
                query={{
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.EventsQuery,
                        select: [
                            ...defaultDataTableColumns(NodeKind.EventsQuery),
                            featureFlag.filters.multivariate
                                ? 'properties.$feature_flag_response'
                                : "if(toString(properties.$feature_flag_response) IN ['1', 'true'], 'true', 'false') -- Feature Flag Response",
                        ],
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
    } = useValues(featureFlagLogic)
    const {
        distributeVariantsEqually,
        addVariant,
        removeVariant,
        setMultivariateEnabled,
        setFeatureFlag,
        saveFeatureFlag,
    } = useActions(featureFlagLogic)

    const filterGroups: FeatureFlagGroupType[] = featureFlag.filters.groups || []

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

    return (
        <>
            {readOnly ? (
                <>
                    <div className="flex flex-col mb-4">
                        <span className="card-secondary">Status</span>
                        <LemonSwitch
                            onChange={(newValue) => {
                                LemonDialog.open({
                                    title: `${newValue === true ? 'Enable' : 'Disable'} this flag?`,
                                    description: `This flag will be immediately ${
                                        newValue === true ? 'rolled out to' : 'rolled back from'
                                    } the users matching the release conditions.`,
                                    primaryButton: {
                                        children: 'Confirm',
                                        type: 'primary',
                                        onClick: () => {
                                            const updatedFlag = { ...featureFlag, active: newValue }
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
                            label="Enabled"
                            checked={featureFlag.active}
                        />
                        <span className="card-secondary mt-4">Type</span>
                        <span>
                            {featureFlag.filters.multivariate
                                ? 'Multiple variants with rollout percentages (A/B/C test)'
                                : 'Release toggle (boolean)'}
                        </span>

                        <span className="card-secondary mt-4">Flag persistence</span>
                        <span>
                            This flag{' '}
                            <b>{featureFlag.ensure_experience_continuity ? 'persists' : 'does not persist'} </b>
                            across authentication events.
                        </span>
                    </div>
                    <LemonDivider className="my-3" />
                    {featureFlag.filters.multivariate && (
                        <>
                            <h3 className="l3">Variant keys</h3>
                            <div className="border rounded p-4 mb-4 bg-bg-light">
                                <div className="grid grid-cols-8 gap-4 font-semibold">
                                    <div className="col-span-2">Key</div>
                                    <div className="col-span-2">Description</div>
                                    <div className="col-span-3">Payload</div>
                                    <div>Rollout</div>
                                </div>
                                <LemonDivider className="my-3" />
                                {variants.map((variant, index) => (
                                    <div key={index}>
                                        <div className="grid grid-cols-8 gap-4">
                                            <div className="col-span-2">
                                                <Lettermark name={alphabet[index]} color={LettermarkColor.Gray} />
                                                <CopyToClipboardInline
                                                    tooltipMessage={null}
                                                    description="key"
                                                    style={{
                                                        marginLeft: '0.5rem',
                                                    }}
                                                    iconStyle={{ color: 'var(--muted-alt)' }}
                                                >
                                                    {variant.key}
                                                </CopyToClipboardInline>
                                            </div>
                                            <div className="col-span-2">
                                                <span className={variant.name ? '' : 'text-muted'}>
                                                    {variant.name || 'There is no description for this variant key'}
                                                </span>
                                            </div>
                                            <div className="col-span-3">
                                                {featureFlag.filters.payloads?.[index] ? (
                                                    <JSONEditorInput
                                                        readOnly={true}
                                                        value={featureFlag.filters.payloads[index]}
                                                    />
                                                ) : (
                                                    <span className="text-muted">
                                                        No payload associated with this variant
                                                    </span>
                                                )}
                                            </div>
                                            <div>{variant.rollout_percentage}%</div>
                                        </div>
                                        {index !== variants.length - 1 && <LemonDivider className="my-3" />}
                                    </div>
                                ))}
                            </div>
                        </>
                    )}
                </>
            ) : (
                <div className="mb-8">
                    <h3 className="l3">Served value</h3>
                    <div className="mb-2">
                        <LemonSegmentedButton
                            size="small"
                            options={[
                                {
                                    label: 'Release toggle (boolean)',
                                    value: 'boolean',
                                    disabledReason:
                                        featureFlag.experiment_set && featureFlag.experiment_set?.length > 0
                                            ? 'This feature flag is associated with an experiment.'
                                            : undefined,
                                },
                                {
                                    label: <span>Multiple variants with rollout percentages (A/B test)</span>,
                                    value: 'multivariate',
                                },
                            ]}
                            onChange={(value) => {
                                if (value === 'boolean' && nonEmptyVariants.length) {
                                    confirmRevertMultivariateEnabled()
                                } else {
                                    setMultivariateEnabled(value === 'multivariate')
                                    focusVariantKeyField(0)
                                }
                            }}
                            value={multivariateEnabled ? 'multivariate' : 'boolean'}
                        />
                    </div>
                    <div className="text-muted mb-4">
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
                        if they match one or more release condition groups.
                    </div>
                </div>
            )}
            {!multivariateEnabled && (
                <div className="mb-6">
                    <h3 className="l3">Payload</h3>
                    {readOnly ? (
                        featureFlag.filters.payloads?.['true'] ? (
                            <JSONEditorInput readOnly={readOnly} value={featureFlag.filters.payloads?.['true']} />
                        ) : (
                            <span>No payload associated with this flag</span>
                        )
                    ) : (
                        <div className="w-1/2">
                            <div className="text-muted mb-4">
                                Specify a payload to be returned when the served value is{' '}
                                <strong>
                                    <code>true</code>
                                </strong>
                            </div>
                            <Group name={['filters', 'payloads']}>
                                <LemonField name="true">
                                    <JSONEditorInput
                                        readOnly={readOnly}
                                        placeholder={'Examples: "A string", 2500, {"key": "value"}'}
                                    />
                                </LemonField>
                            </Group>
                        </div>
                    )}
                </div>
            )}
            {!readOnly && multivariateEnabled && (
                <div className="feature-flag-variants">
                    <h3 className="l4">Variant keys</h3>
                    <span>The rollout percentage of feature flag variants must add up to 100%</span>
                    <div className="VariantFormList space-y-2">
                        <div className="VariantFormList__row grid label-row gap-2 items-center">
                            <div />
                            <div className="col-span-4">Variant key</div>
                            <div className="col-span-6">Description</div>
                            <div className="col-span-8">
                                <div className="flex flex-col">
                                    <b>Payload</b>
                                    <span className="text-muted font-normal">
                                        Specify return payload when the variant key matches
                                    </span>
                                </div>
                            </div>
                            <div className="col-span-4 flex items-center gap-1">
                                <span>Rollout</span>
                                <LemonButton onClick={distributeVariantsEqually}>(Redistribute)</LemonButton>
                            </div>
                        </div>
                        {variants.map((variant, index) => (
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
                                                disabled={
                                                    !!(
                                                        featureFlag.experiment_set &&
                                                        featureFlag.experiment_set?.length > 0
                                                    )
                                                }
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
                                                        onChange={onChange}
                                                        value={value}
                                                        placeholder={'{"key": "value"}'}
                                                    />
                                                )
                                            }}
                                        </LemonField>
                                    </div>
                                    <div className="col-span-3">
                                        <LemonField name={['multivariate', 'variants', index, 'rollout_percentage']}>
                                            {({ value, onChange }) => (
                                                <div>
                                                    <LemonInput
                                                        type="number"
                                                        min={0}
                                                        max={100}
                                                        value={value}
                                                        onChange={(changedValue) => {
                                                            if (changedValue !== null) {
                                                                const valueInt =
                                                                    changedValue !== undefined
                                                                        ? parseInt(changedValue.toString())
                                                                        : 0
                                                                if (!isNaN(valueInt)) {
                                                                    onChange(valueInt)
                                                                }
                                                            }
                                                        }}
                                                    />
                                                    {filterGroups.filter((group) => group.variant === variant.key)
                                                        .length > 0 && (
                                                        <span className="text-muted text-xs">
                                                            Overridden by{' '}
                                                            <strong>
                                                                {variantConcatWithPunctuation(
                                                                    filterGroups
                                                                        .filter(
                                                                            (group) =>
                                                                                group.variant != null &&
                                                                                group.variant === variant.key
                                                                        )
                                                                        .map(
                                                                            (variant) =>
                                                                                'Set ' +
                                                                                (filterGroups.findIndex(
                                                                                    (group) => group === variant
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
                                                    featureFlag.experiment_set && featureFlag.experiment_set?.length > 0
                                                        ? 'Cannot delete variants from a feature flag that is part of an experiment'
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
                                Percentage rollouts for variants must sum to 100 (currently {variantRolloutSum}
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
                                featureFlag.experiment_set && featureFlag.experiment_set?.length > 0
                                    ? 'Cannot add variants to a feature flag that is part of an experiment. To update variants, create a new experiment.'
                                    : undefined
                            }
                            tooltipPlacement="top-start"
                            center
                        >
                            Add variant
                        </LemonButton>
                    </div>
                </div>
            )}
        </>
    )
}
