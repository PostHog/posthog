import { useEffect, useState } from 'react'
import { Form, Group } from 'kea-forms'
import { Row, Col, Radio, Popconfirm, Skeleton, Card } from 'antd'
import { useActions, useValues } from 'kea'
import { alphabet, capitalizeFirstLetter } from 'lib/utils'
import { LockOutlined } from '@ant-design/icons'
import { featureFlagLogic } from './featureFlagLogic'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { PageHeader } from 'lib/components/PageHeader'
import './FeatureFlag.scss'
import { IconDelete, IconPlus, IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { SceneExport } from 'scenes/sceneTypes'
import { UTM_TAGS } from 'scenes/feature-flags/FeatureFlagSnippets'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { userLogic } from 'scenes/userLogic'
import {
    AnyPropertyFilter,
    AvailableFeature,
    DashboardPlacement,
    PropertyFilterType,
    PropertyOperator,
    Resource,
    FeatureFlagType,
    ReplayTabs,
    FeatureFlagGroupType,
    NotebookNodeType,
} from '~/types'
import { Link } from 'lib/lemon-ui/Link'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Field } from 'lib/forms/Field'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { urls } from 'scenes/urls'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { router } from 'kea-router'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { FeatureFlagsTab, featureFlagsLogic } from './featureFlagsLogic'
import { RecentFeatureFlagInsights } from './RecentFeatureFlagInsightsCard'
import { NotFound } from 'lib/components/NotFound'
import { FeatureFlagAutoRollback } from './FeatureFlagAutoRollout'
import { featureFlagPermissionsLogic } from './featureFlagPermissionsLogic'
import { ResourcePermission } from 'scenes/ResourcePermissionModal'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { JSONEditorInput } from 'scenes/feature-flags/JSONEditorInput'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { tagsModel } from '~/models/tagsModel'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { EmptyDashboardComponent } from 'scenes/dashboard/EmptyDashboardComponent'
import { FeatureFlagCodeExample } from './FeatureFlagCodeExample'
import { billingLogic } from 'scenes/billing/billingLogic'
import { AnalysisTab } from './FeatureFlagAnalysisTab'
import { NodeKind } from '~/queries/schema'
import { Query } from '~/queries/Query/Query'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { PostHogFeature } from 'posthog-js/react'
import { concatWithPunctuation } from 'scenes/insights/utils'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { FeatureFlagReleaseConditions } from './FeatureFlagReleaseConditions'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'

export const scene: SceneExport = {
    component: FeatureFlag,
    logic: featureFlagLogic,
    paramsToProps: ({ params: { id } }): (typeof featureFlagLogic)['props'] => ({
        id: id && id !== 'new' ? parseInt(id) : 'new',
    }),
}

function focusVariantKeyField(index: number): void {
    setTimeout(
        () => document.querySelector<HTMLElement>(`.variant-form-list input[data-key-index="${index}"]`)?.focus(),
        50
    )
}

export function FeatureFlag({ id }: { id?: string } = {}): JSX.Element {
    const { props, featureFlag, featureFlagLoading, featureFlagMissing, isEditingFlag, recordingFilterForFlag } =
        useValues(featureFlagLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const { deleteFeatureFlag, editFeatureFlag, loadFeatureFlag, triggerFeatureFlagUpdate } =
        useActions(featureFlagLogic)

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

    const [activeTab, setActiveTab] = useState(FeatureFlagsTab.OVERVIEW)
    const [advancedSettingsExpanded, setAdvancedSettingsExpanded] = useState(false)

    const isNewFeatureFlag = id === 'new' || id === undefined

    if (featureFlagMissing) {
        return <NotFound object={'feature flag'} />
    }
    if (featureFlagLoading) {
        return (
            // TODO: This should be skeleton loaders
            <SpinnerOverlay sceneLevel />
        )
    }

    const tabs = [
        {
            label: 'Overview',
            key: FeatureFlagsTab.OVERVIEW,
            content: (
                <>
                    <Row>
                        <Col span={13}>
                            <FeatureFlagRollout readOnly />
                            {featureFlag.filters.super_groups && <FeatureFlagReleaseConditions readOnly isSuper />}
                            <FeatureFlagReleaseConditions readOnly />
                            {featureFlags[FEATURE_FLAGS.AUTO_ROLLBACK_FEATURE_FLAGS] && (
                                <FeatureFlagAutoRollback readOnly />
                            )}
                        </Col>
                        <Col span={11} className="pl-4">
                            <RecentFeatureFlagInsights />
                            <div className="my-4" />
                        </Col>
                    </Row>
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

    if (featureFlags[FEATURE_FLAGS.ROLE_BASED_ACCESS] && featureFlag.can_edit) {
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
                        logic={featureFlagLogic}
                        props={props}
                        formKey="featureFlag"
                        enableFormOnSubmit
                        className="space-y-4"
                    >
                        <PageHeader
                            title={isNewFeatureFlag ? 'New feature flag' : featureFlag.key || 'Untitled'}
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
                                        disabled={featureFlagLoading}
                                    >
                                        Cancel
                                    </LemonButton>
                                    <LemonButton
                                        type="primary"
                                        data-attr="save-feature-flag"
                                        htmlType="submit"
                                        loading={featureFlagLoading}
                                        disabled={featureFlagLoading}
                                    >
                                        Save
                                    </LemonButton>
                                </div>
                            }
                        />
                        <LemonDivider />
                        {featureFlag.experiment_set && featureFlag.experiment_set?.length > 0 && (
                            <LemonBanner type="warning">
                                This feature flag is linked to an experiment. Edit settings here only for advanced
                                functionality. If unsure, go back to{' '}
                                <Link to={urls.experiment(featureFlag.experiment_set[0])}>
                                    the experiment creation screen.
                                </Link>
                            </LemonBanner>
                        )}
                        <Row gutter={16} style={{ marginBottom: 32 }}>
                            <Col span={12} className="space-y-4">
                                <Field
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
                                            <span style={{ fontSize: 13 }} className="text-muted">
                                                Feature flag keys must be unique
                                            </span>
                                        </>
                                    )}
                                </Field>

                                <Field name="name" label="Description">
                                    <LemonTextArea
                                        className="ph-ignore-input"
                                        data-attr="feature-flag-description"
                                        defaultValue={featureFlag.name || ''}
                                    />
                                </Field>
                                {hasAvailableFeature(AvailableFeature.TAGGING) && (
                                    <Field name="tags" label="Tags">
                                        {({ value, onChange }) => {
                                            return (
                                                <ObjectTags
                                                    tags={value}
                                                    onChange={(_, tags) => onChange(tags)}
                                                    saving={featureFlagLoading}
                                                    tagsAvailable={tags.filter(
                                                        (tag) => !featureFlag.tags?.includes(tag)
                                                    )}
                                                    className="insight-metadata-tags"
                                                />
                                            )
                                        }}
                                    </Field>
                                )}
                                <Field name="active">
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
                                </Field>
                                <Field name="ensure_experience_continuity">
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
                                                If your feature flag is applied prior to an identify or authentication
                                                event, use this to ensure that feature flags are not reset after a
                                                person is identified. This ensures the experience for the anonymous
                                                person is carried forward to the authenticated person.{' '}
                                                <Link
                                                    to="https://posthog.com/manual/feature-flags#persisting-feature-flags-across-authentication-steps"
                                                    target="_blank"
                                                >
                                                    Learn more
                                                </Link>
                                            </div>
                                        </div>
                                    )}
                                </Field>
                            </Col>
                        </Row>
                        <LemonDivider />
                        <FeatureFlagRollout />
                        <LemonDivider />
                        <FeatureFlagReleaseConditions />
                        <LemonDivider />
                        <FeatureFlagCodeExample featureFlag={featureFlag} />
                        <LemonDivider />
                        {isNewFeatureFlag && (
                            <>
                                <div>
                                    <LemonButton
                                        fullWidth
                                        status="stealth"
                                        onClick={() => setAdvancedSettingsExpanded(!advancedSettingsExpanded)}
                                        sideIcon={advancedSettingsExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
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
                                        {featureFlags[FEATURE_FLAGS.ROLE_BASED_ACCESS] && (
                                            <Card title="Permissions" className="mb-4">
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
                                            </Card>
                                        )}
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
                                disabled={featureFlagLoading}
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                data-attr="save-feature-flag"
                                htmlType="submit"
                                loading={featureFlagLoading}
                                disabled={featureFlagLoading}
                            >
                                Save
                            </LemonButton>
                        </div>
                    </Form>
                ) : (
                    <>
                        {featureFlagLoading ? (
                            <Skeleton active />
                        ) : (
                            <>
                                <PageHeader
                                    notebookProps={{
                                        href: urls.featureFlag(id),
                                    }}
                                    title={
                                        <div className="flex items-center gap-2 mb-2">
                                            {featureFlag.key || 'Untitled'}
                                            <CopyToClipboardInline
                                                explicitValue={featureFlag.key}
                                                iconStyle={{ color: 'var(--muted-alt)' }}
                                            />
                                            <div className="flex">
                                                {featureFlag.active ? (
                                                    <LemonTag type="success" className="uppercase">
                                                        Enabled
                                                    </LemonTag>
                                                ) : (
                                                    <LemonTag type="default" className="uppercase">
                                                        Disabled
                                                    </LemonTag>
                                                )}
                                            </div>
                                        </div>
                                    }
                                    description={
                                        <>
                                            {featureFlag.name ? (
                                                <span style={{ fontStyle: 'normal' }}>{featureFlag.name}</span>
                                            ) : (
                                                'There is no description for this feature flag.'
                                            )}
                                        </>
                                    }
                                    caption={
                                        <>
                                            {featureFlag?.tags && (
                                                <>
                                                    {featureFlag.can_edit ? (
                                                        <ObjectTags
                                                            tags={featureFlag.tags}
                                                            onChange={(_, tags) => {
                                                                triggerFeatureFlagUpdate({ tags })
                                                            }}
                                                            saving={featureFlagLoading}
                                                            tagsAvailable={tags.filter(
                                                                (tag) => !featureFlag.tags?.includes(tag)
                                                            )}
                                                            className="insight-metadata-tags"
                                                        />
                                                    ) : featureFlag.tags.length ? (
                                                        <ObjectTags
                                                            tags={featureFlag.tags}
                                                            saving={featureFlagLoading}
                                                            staticOnly
                                                            className="insight-metadata-tags"
                                                        />
                                                    ) : null}
                                                </>
                                            )}
                                        </>
                                    }
                                    buttons={
                                        <>
                                            <div className="flex items-center gap-2 mb-2">
                                                <NotebookSelectButton
                                                    resource={{
                                                        type: NotebookNodeType.FeatureFlag,
                                                        attrs: { id: featureFlag.id },
                                                    }}
                                                    type="secondary"
                                                />
                                                <LemonButton
                                                    to={urls.replay(ReplayTabs.Recent, recordingFilterForFlag)}
                                                    type="secondary"
                                                >
                                                    View Recordings
                                                </LemonButton>
                                                <LemonDivider vertical />
                                                <LemonButton
                                                    data-attr="delete-feature-flag"
                                                    status="danger"
                                                    type="secondary"
                                                    onClick={() => {
                                                        deleteFeatureFlag(featureFlag)
                                                    }}
                                                    disabledReason={
                                                        featureFlagLoading
                                                            ? 'Loading...'
                                                            : !featureFlag.can_edit
                                                            ? "You have only 'View' access for this feature flag. To make changes, please contact the flag's creator."
                                                            : (featureFlag.features?.length || 0) > 0
                                                            ? 'This feature flag is in use with an early access feature. Delete the early access feature to delete this flag'
                                                            : null
                                                    }
                                                >
                                                    Delete feature flag
                                                </LemonButton>
                                                <LemonButton
                                                    data-attr="edit-feature-flag"
                                                    type="secondary"
                                                    tooltip={
                                                        featureFlags[FEATURE_FLAGS.ROLE_BASED_ACCESS] &&
                                                        !featureFlag.can_edit &&
                                                        "You have only 'View' access for this feature flag. To make changes, please contact the flag's creator."
                                                    }
                                                    onClick={() => {
                                                        editFeatureFlag(true)
                                                    }}
                                                    disabled={featureFlagLoading || !featureFlag.can_edit}
                                                >
                                                    Edit
                                                </LemonButton>
                                            </div>
                                        </>
                                    }
                                />
                                <LemonTabs activeKey={activeTab} onChange={setActiveTab} tabs={tabs} />
                            </>
                        )}
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
    const { receivedErrorsFromAPI, dashboard } = useValues(
        dashboardLogic({ id: dashboardId, placement: DashboardPlacement.FeatureFlag })
    )
    const connectedDashboardExists = dashboardId && !receivedErrorsFromAPI

    const { closeEnrichAnalyticsNotice } = useActions(featureFlagsLogic)
    const { enrichAnalyticsNoticeAcknowledged } = useValues(featureFlagsLogic)

    useEffect(() => {
        if (
            connectedDashboardExists &&
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
            {connectedDashboardExists ? (
                <>
                    {!hasEnrichedAnalytics && !enrichAnalyticsNoticeAcknowledged && (
                        <LemonBanner type="info" className="mb-3" onClose={() => closeEnrichAnalyticsNotice()}>
                            Get richer insights automatically by{' '}
                            <Link to="https://posthog.com/docs/libraries/js#enriched-analytics" target="_blank">
                                enabling enriched analytics for flags{' '}
                            </Link>
                        </LemonBanner>
                    )}
                    <Dashboard id={dashboardId.toString()} placement={DashboardPlacement.FeatureFlag} />
                </>
            ) : (
                <div>
                    <b>Dashboard</b>
                    <div className="text-muted mb-2">{`There is currently no connected dashboard to this feature flag. If there was previously a connected dashboard, it may have been deleted.`}</div>
                    {featureFlagLoading ? (
                        <EmptyDashboardComponent loading={true} canEdit={false} />
                    ) : (
                        <LemonButton type={'primary'} onClick={() => generateUsageDashboard()}>
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
    } else {
        return `${phrases[0]} and ${phrases.length - 1} more sets`
    }
}

function FeatureFlagRollout({ readOnly }: { readOnly?: boolean }): JSX.Element {
    const {
        multivariateEnabled,
        variants,
        areVariantRolloutsValid,
        featureFlagLoading,
        variantRolloutSum,
        nonEmptyVariants,
        aggregationTargetName,
        featureFlag,
    } = useValues(featureFlagLogic)
    const { distributeVariantsEqually, addVariant, removeVariant, setMultivariateEnabled } =
        useActions(featureFlagLogic)
    const [showVariantDiscardWarning, setShowVariantDiscardWarning] = useState(false)
    const { hasAvailableFeature } = useValues(userLogic)
    const { upgradeLink } = useValues(billingLogic)

    const filterGroups: FeatureFlagGroupType[] = featureFlag.filters.groups || []

    return (
        <>
            {readOnly ? (
                <>
                    <div className="flex flex-col mb-4">
                        <span className="card-secondary">Type</span>
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
                                <Row gutter={16} className="font-semibold">
                                    <Col span={6}>Key</Col>
                                    <Col span={6}>Description</Col>
                                    <Col span={9}>Payload</Col>
                                    <Col span={3}>Rollout</Col>
                                </Row>
                                <LemonDivider className="my-3" />
                                {variants.map((variant, index) => (
                                    <div key={index}>
                                        <Row gutter={16}>
                                            <Col span={6}>
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
                                            </Col>
                                            <Col span={6}>
                                                <span className={variant.name ? '' : 'text-muted'}>
                                                    {variant.name || 'There is no description for this variant key'}
                                                </span>
                                            </Col>
                                            <Col span={9}>
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
                                            </Col>
                                            <Col span={3}>{variant.rollout_percentage}%</Col>
                                        </Row>
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
                        <Popconfirm
                            placement="top"
                            title="Change value type? The variants below will be lost."
                            disabled={featureFlagLoading}
                            visible={showVariantDiscardWarning}
                            onConfirm={() => {
                                setMultivariateEnabled(false)
                                setShowVariantDiscardWarning(false)
                            }}
                            onCancel={() => setShowVariantDiscardWarning(false)}
                            okText="OK"
                            cancelText="Cancel"
                        >
                            <Radio.Group
                                options={[
                                    {
                                        label: 'Release toggle (boolean)',
                                        value: false,
                                        disabled: !!(
                                            featureFlag.experiment_set && featureFlag.experiment_set?.length > 0
                                        ),
                                    },
                                    {
                                        label: (
                                            <Tooltip
                                                title={
                                                    hasAvailableFeature(AvailableFeature.MULTIVARIATE_FLAGS)
                                                        ? ''
                                                        : 'This feature is not available on your current plan.'
                                                }
                                            >
                                                <div>
                                                    {!hasAvailableFeature(AvailableFeature.MULTIVARIATE_FLAGS) && (
                                                        <Link to={upgradeLink} target="_blank">
                                                            <LockOutlined
                                                                style={{
                                                                    marginRight: 4,
                                                                    color: 'var(--warning)',
                                                                }}
                                                            />
                                                        </Link>
                                                    )}
                                                    Multiple variants with rollout percentages (A/B test)
                                                </div>
                                            </Tooltip>
                                        ),
                                        value: true,
                                        disabled: !hasAvailableFeature(AvailableFeature.MULTIVARIATE_FLAGS),
                                    },
                                ]}
                                onChange={(e) => {
                                    const { value } = e.target
                                    if (value === false && nonEmptyVariants.length) {
                                        setShowVariantDiscardWarning(true)
                                    } else {
                                        setMultivariateEnabled(value)
                                        focusVariantKeyField(0)
                                    }
                                }}
                                value={multivariateEnabled}
                                optionType="button"
                            />
                        </Popconfirm>
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
                        <Row gutter={16}>
                            <Col span={12}>
                                <div className="text-muted mb-4">
                                    Specify a payload to be returned when the served value is{' '}
                                    <strong>
                                        <code>true</code>
                                    </strong>
                                </div>
                                <Group name={['filters', 'payloads']}>
                                    <Field name="true">
                                        <JSONEditorInput
                                            readOnly={readOnly}
                                            placeholder={'Examples: "A string", 2500, {"key": "value"}'}
                                        />
                                    </Field>
                                </Group>
                            </Col>
                        </Row>
                    )}
                </div>
            )}
            {!readOnly && multivariateEnabled && (
                <div className="feature-flag-variants">
                    <h3 className="l4">Variant keys</h3>
                    <span>The rollout percentage of feature flag variants must add up to 100%</span>
                    <div className="variant-form-list space-y-2">
                        <Row gutter={8} className="label-row">
                            <Col span={1} />
                            <Col span={4}>Variant key</Col>
                            <Col span={6}>Description</Col>
                            <Col span={8}>
                                <div style={{ display: 'flex', flexDirection: 'column', fontWeight: 'normal' }}>
                                    <b>Payload</b>
                                    <span className="text-muted">
                                        Specify return payload when the variant key matches
                                    </span>
                                </div>
                            </Col>
                            <Col span={4}>
                                Rollout
                                <LemonButton type="tertiary" onClick={distributeVariantsEqually}>
                                    (Redistribute)
                                </LemonButton>
                            </Col>
                        </Row>
                        {variants.map((variant, index) => (
                            <Group key={index} name="filters">
                                <Row gutter={8} align="top">
                                    <Col span={1} style={{ paddingTop: 8 }}>
                                        <Lettermark name={alphabet[index]} color={LettermarkColor.Gray} />
                                    </Col>
                                    <Col span={4}>
                                        <Field name={['multivariate', 'variants', index, 'key']}>
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
                                        </Field>
                                    </Col>
                                    <Col span={6}>
                                        <Field name={['multivariate', 'variants', index, 'name']}>
                                            <LemonInput
                                                data-attr="feature-flag-variant-name"
                                                className="ph-ignore-input"
                                                placeholder="Description"
                                            />
                                        </Field>
                                    </Col>
                                    <Col span={8}>
                                        <Field name={['payloads', index]}>
                                            {({ value, onChange }) => {
                                                return (
                                                    <JSONEditorInput
                                                        onChange={onChange}
                                                        value={value}
                                                        placeholder={'{"key": "value"}'}
                                                    />
                                                )
                                            }}
                                        </Field>
                                    </Col>
                                    <Col span={3}>
                                        <Field name={['multivariate', 'variants', index, 'rollout_percentage']}>
                                            {({ value, onChange }) => (
                                                <div>
                                                    <LemonInput
                                                        type="number"
                                                        min={0}
                                                        max={100}
                                                        value={value}
                                                        onChange={(changedValue) => {
                                                            if (changedValue !== null && changedValue !== undefined) {
                                                                const valueInt = parseInt(changedValue.toString())
                                                                if (!isNaN(valueInt)) {
                                                                    onChange(valueInt)
                                                                }
                                                            }
                                                        }}
                                                    />
                                                    {filterGroups.filter((group) => group.variant === variant.key)
                                                        .length > 0 && (
                                                        <span style={{ fontSize: 11 }} className="text-muted">
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
                                        </Field>
                                    </Col>
                                    <Col span={2} style={{ paddingTop: 8 }}>
                                        <Row>
                                            {variants.length > 1 && (
                                                <LemonButton
                                                    icon={<IconDelete />}
                                                    status="primary-alt"
                                                    data-attr={`delete-prop-filter-${index}`}
                                                    noPadding
                                                    onClick={() => removeVariant(index)}
                                                    disabledReason={
                                                        featureFlag.experiment_set &&
                                                        featureFlag.experiment_set?.length > 0
                                                            ? 'Cannot delete variants from a feature flag that is part of an experiment'
                                                            : undefined
                                                    }
                                                    tooltipPlacement="topRight"
                                                />
                                            )}
                                        </Row>
                                    </Col>
                                </Row>
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
                            tooltipPlacement="topLeft"
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
