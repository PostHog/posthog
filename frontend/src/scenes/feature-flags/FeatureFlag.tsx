import { useState } from 'react'
import { Form, Group } from 'kea-forms'
import { Row, Col, Radio, InputNumber, Popconfirm, Select, Tabs, Skeleton, Card } from 'antd'
import { useActions, useValues } from 'kea'
import { alphabet, capitalizeFirstLetter, humanFriendlyNumber } from 'lib/utils'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { LockOutlined } from '@ant-design/icons'
import { defaultEntityFilterOnFlag, featureFlagLogic } from './featureFlagLogic'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { PageHeader } from 'lib/components/PageHeader'
import './FeatureFlag.scss'
import {
    IconOpenInNew,
    IconCopy,
    IconDelete,
    IconPlus,
    IconPlusMini,
    IconSubArrowRight,
    IconErrorOutline,
    IconUnfoldLess,
    IconUnfoldMore,
} from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { SceneExport } from 'scenes/sceneTypes'
import { UTM_TAGS } from 'scenes/feature-flags/FeatureFlagSnippets'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { groupsModel } from '~/models/groupsModel'
import { GroupsIntroductionOption } from 'lib/introductions/GroupsIntroductionOption'
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
} from '~/types'
import { Link } from 'lib/lemon-ui/Link'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Field } from 'lib/forms/Field'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { urls } from 'scenes/urls'
import { Spinner, SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { router } from 'kea-router'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { FEATURE_FLAGS, INSTANTLY_AVAILABLE_PROPERTIES } from 'lib/constants'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { FeatureFlagsTab } from './featureFlagsLogic'
import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { RecentFeatureFlagInsights } from './RecentFeatureFlagInsightsCard'
import { NotFound } from 'lib/components/NotFound'
import { cohortsModel } from '~/models/cohortsModel'
import { FeatureFlagAutoRollback } from './FeatureFlagAutoRollout'
import { LemonSelect } from '@posthog/lemon-ui'
import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
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
import clsx from 'clsx'
import { AnalysisTab } from './FeatureFlagAnalysisTab'
import { NodeKind } from '~/queries/schema'
import { Query } from '~/queries/Query/Query'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { PostHogFeature } from 'posthog-js/react'

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
    const { props, featureFlag, featureFlagLoading, featureFlagMissing, isEditingFlag } = useValues(featureFlagLogic)
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
                                                <a
                                                    href={`https://posthog.com/docs/features/feature-flags${UTM_TAGS}#feature-flag-persistence`}
                                                    target="_blank"
                                                    rel="noopener"
                                                >
                                                    {' '}
                                                    affect the persistence of your flag <IconOpenInNew />
                                                </a>
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
                                        status="default-dark"
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
                                                {featureFlags[FEATURE_FLAGS.RECORDINGS_ON_FEATURE_FLAGS] && (
                                                    <>
                                                        <LemonButton
                                                            to={urls.replay(ReplayTabs.Recent, {
                                                                events: defaultEntityFilterOnFlag(featureFlag.key)
                                                                    .events,
                                                            })}
                                                            type="secondary"
                                                        >
                                                            View Recordings
                                                            <LemonTag type="warning" className="uppercase ml-2 mr-2">
                                                                Beta
                                                            </LemonTag>
                                                        </LemonButton>
                                                        <LemonDivider vertical />
                                                    </>
                                                )}
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
                                <Tabs
                                    activeKey={activeTab}
                                    destroyInactiveTabPane
                                    onChange={(t) => setActiveTab(t as FeatureFlagsTab)}
                                >
                                    <Tabs.TabPane tab="Overview" key="overview">
                                        <Row>
                                            <Col span={13}>
                                                <FeatureFlagRollout readOnly />
                                                {featureFlag.filters.super_groups && (
                                                    <FeatureFlagReleaseConditions readOnly isSuper />
                                                )}
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
                                    </Tabs.TabPane>
                                    {featureFlag.key && id && (
                                        <Tabs.TabPane tab={<div>Usage</div>} key="usage">
                                            <UsageTab id={id} featureFlag={featureFlag} />
                                        </Tabs.TabPane>
                                    )}

                                    {featureFlags[FEATURE_FLAGS.FF_DASHBOARD_TEMPLATES] && featureFlag.key && id && (
                                        <Tabs.TabPane
                                            tab={
                                                <div className="flex flex-row">
                                                    <div>Analysis</div>
                                                    <LemonTag className="ml-1 float-right uppercase" type="warning">
                                                        {' '}
                                                        Beta
                                                    </LemonTag>
                                                </div>
                                            }
                                            key="analysis"
                                        >
                                            <PostHogFeature flag={FEATURE_FLAGS.FF_DASHBOARD_TEMPLATES} match={true}>
                                                <AnalysisTab id={id} featureFlag={featureFlag} />
                                            </PostHogFeature>
                                        </Tabs.TabPane>
                                    )}

                                    {featureFlag.id && (
                                        <Tabs.TabPane tab="History" key="history">
                                            <ActivityLog scope={ActivityScope.FEATURE_FLAG} id={featureFlag.id} />
                                        </Tabs.TabPane>
                                    )}
                                    {featureFlags[FEATURE_FLAGS.ROLE_BASED_ACCESS] && featureFlag.can_edit && (
                                        <Tabs.TabPane tab="Permissions" key="permissions">
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
                                        </Tabs.TabPane>
                                    )}
                                </Tabs>
                            </>
                        )}
                    </>
                )}
            </div>
        </>
    )
}

function UsageTab({ featureFlag }: { id: string; featureFlag: FeatureFlagType }): JSX.Element {
    const { key: featureFlagKey, usage_dashboard: dashboardId } = featureFlag
    const { generateUsageDashboard } = useActions(featureFlagLogic)
    const { featureFlagLoading } = useValues(featureFlagLogic)
    const { receivedErrorsFromAPI } = useValues(
        dashboardLogic({ id: dashboardId, placement: DashboardPlacement.FeatureFlag })
    )
    const connectedDashboardExists = dashboardId && !receivedErrorsFromAPI
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
                <Dashboard id={dashboardId.toString()} placement={DashboardPlacement.FeatureFlag} />
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

interface FeatureFlagReadOnlyProps {
    readOnly?: boolean
    isSuper?: boolean
}

function FeatureFlagRollout({ readOnly }: FeatureFlagReadOnlyProps): JSX.Element {
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
                        {variants.map((_, index) => (
                            <Group key={index} name="filters">
                                <Row gutter={8} align="middle">
                                    <Col span={1}>
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
                                            )}
                                        </Field>
                                    </Col>
                                    <Col span={2}>
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

function FeatureFlagReleaseConditions({ readOnly, isSuper }: FeatureFlagReadOnlyProps): JSX.Element {
    const { showGroupsOptions, aggregationLabel } = useValues(groupsModel)
    const {
        aggregationTargetName,
        featureFlag,
        groupTypes,
        taxonomicGroupTypes,
        nonEmptyVariants,
        propertySelectErrors,
        computeBlastRadiusPercentage,
        affectedUsers,
        totalUsers,
    } = useValues(featureFlagLogic)
    const {
        setAggregationGroupTypeIndex,
        updateConditionSet,
        duplicateConditionSet,
        removeConditionSet,
        addConditionSet,
    } = useActions(featureFlagLogic)
    const { cohortsById } = useValues(cohortsModel)
    const { featureFlags } = useValues(enabledFeaturesLogic)

    const _filter_groups: FeatureFlagGroupType[] = isSuper
        ? featureFlag.filters.super_groups || []
        : featureFlag.filters.groups
    // :KLUDGE: Match by select only allows Select.Option as children, so render groups option directly rather than as a child
    const matchByGroupsIntroductionOption = GroupsIntroductionOption({ value: -2 })
    const hasNonInstantProperty = (properties: AnyPropertyFilter[]): boolean => {
        return !!properties.find(
            (property) => property.type === 'cohort' || !INSTANTLY_AVAILABLE_PROPERTIES.includes(property.key || '')
        )
    }

    const isEarlyAccessFeatureCondition = (group: FeatureFlagGroupType): boolean => {
        return !!(
            featureFlag.features?.length &&
            featureFlag.features?.length > 0 &&
            group.properties.some((property) => property.key === '$feature_enrollment/' + featureFlag.key)
        )
    }

    const renderReleaseConditionGroup = (group: FeatureFlagGroupType, index: number): JSX.Element => {
        return (
            <Col span={24} md={24} key={`${index}-${_filter_groups.length}`}>
                {index > 0 && <div className="condition-set-separator">OR</div>}
                <div className={clsx('mb-4', 'border', 'rounded', 'p-4')}>
                    <Row align="middle" justify="space-between">
                        <Row align="middle">
                            <span className="simple-tag tag-light-blue font-medium mr-2">Set {index + 1}</span>
                            <div>
                                {group.properties?.length ? (
                                    <>
                                        {readOnly ? (
                                            <>
                                                Match <b>{aggregationTargetName}</b> against <b>all</b> criteria
                                            </>
                                        ) : (
                                            <>
                                                Matching <b>{aggregationTargetName}</b> against the criteria
                                            </>
                                        )}
                                    </>
                                ) : (
                                    <>
                                        Condition set will match <b>all {aggregationTargetName}</b>
                                    </>
                                )}
                            </div>
                        </Row>
                        {!readOnly && (
                            <Row>
                                <LemonButton
                                    icon={<IconCopy />}
                                    status="muted"
                                    noPadding
                                    onClick={() => duplicateConditionSet(index)}
                                />
                                {!isEarlyAccessFeatureCondition(group) && _filter_groups.length > 1 && (
                                    <LemonButton
                                        icon={<IconDelete />}
                                        status="muted"
                                        noPadding
                                        onClick={() => removeConditionSet(index)}
                                    />
                                )}
                            </Row>
                        )}
                    </Row>
                    <LemonDivider className="my-3" />
                    {!readOnly && hasNonInstantProperty(group.properties) && (
                        <LemonBanner type="info" className="mt-3 mb-3">
                            These properties aren't immediately available on first page load for unidentified persons.
                            This feature flag requires that at least one event is sent prior to becoming available to
                            your product or website.{' '}
                            <a href="https://posthog.com/docs/integrate/client/js#bootstrapping-flags" target="_blank">
                                {' '}
                                Learn more about how to make feature flags available instantly.
                            </a>
                        </LemonBanner>
                    )}

                    {readOnly ? (
                        <>
                            {group.properties.map((property, idx) => (
                                <>
                                    <div className="feature-flag-property-display" key={idx}>
                                        {idx === 0 ? (
                                            <LemonButton
                                                icon={<IconSubArrowRight className="arrow-right" />}
                                                status="muted"
                                                size="small"
                                            />
                                        ) : (
                                            <LemonButton
                                                icon={<span className="text-sm">&</span>}
                                                status="muted"
                                                size="small"
                                            />
                                        )}
                                        <span className="simple-tag tag-light-blue text-primary-alt">
                                            {property.type === 'cohort' ? 'Cohort' : property.key}{' '}
                                        </span>
                                        {isPropertyFilterWithOperator(property) ? (
                                            <span>{allOperatorsToHumanName(property.operator)} </span>
                                        ) : null}

                                        {property.type === 'cohort' ? (
                                            <a
                                                href={urls.cohort(property.value)}
                                                target="_blank"
                                                rel="noopener"
                                                className="simple-tag tag-light-blue text-primary-alt display-value"
                                            >
                                                {(property.value && cohortsById[property.value]?.name) ||
                                                    `ID ${property.value}`}
                                            </a>
                                        ) : (
                                            [
                                                ...(Array.isArray(property.value) ? property.value : [property.value]),
                                            ].map((val, idx) => (
                                                <span
                                                    key={idx}
                                                    className="simple-tag tag-light-blue text-primary-alt display-value"
                                                >
                                                    {val}
                                                </span>
                                            ))
                                        )}
                                    </div>
                                </>
                            ))}
                        </>
                    ) : (
                        <div>
                            <PropertyFilters
                                orFiltering={true}
                                pageKey={`feature-flag-${featureFlag.id}-${index}-${_filter_groups.length}-${
                                    featureFlag.filters.aggregation_group_type_index ?? ''
                                }`}
                                propertyFilters={group?.properties}
                                logicalRowDivider
                                addButton={
                                    <LemonButton icon={<IconPlusMini />} sideIcon={null} noPadding>
                                        Add condition
                                    </LemonButton>
                                }
                                onChange={(properties) => updateConditionSet(index, undefined, properties)}
                                taxonomicGroupTypes={taxonomicGroupTypes}
                                hasRowOperator={false}
                                sendAllKeyUpdates
                                errorMessages={
                                    propertySelectErrors?.[index]?.properties?.some((message) => !!message.value)
                                        ? propertySelectErrors[index].properties.map((message, index) => {
                                              return message.value ? (
                                                  <div
                                                      key={index}
                                                      className="text-danger flex items-center gap-1 text-sm"
                                                  >
                                                      <IconErrorOutline className="text-xl" /> {message.value}
                                                  </div>
                                              ) : (
                                                  <></>
                                              )
                                          })
                                        : null
                                }
                            />
                        </div>
                    )}
                    {(!readOnly || (readOnly && group.properties?.length > 0)) && <LemonDivider className="my-3" />}
                    {readOnly ? (
                        <LemonTag
                            type={
                                _filter_groups.length == 1
                                    ? group.rollout_percentage == null || group.rollout_percentage == 100
                                        ? 'highlight'
                                        : group.rollout_percentage == 0
                                        ? 'caution'
                                        : 'none'
                                    : 'none'
                            }
                        >
                            <div className="text-sm ">
                                Rolled out to{' '}
                                <b>{group.rollout_percentage != null ? group.rollout_percentage : 100}%</b> of{' '}
                                <b>{aggregationTargetName}</b> in this set.{' '}
                            </div>
                        </LemonTag>
                    ) : (
                        <div className="feature-flag-form-row">
                            <div className="centered">
                                Roll out to{' '}
                                <InputNumber
                                    style={{ width: 100, marginLeft: 8, marginRight: 8 }}
                                    onChange={(value): void => {
                                        updateConditionSet(index, value as number)
                                    }}
                                    value={group.rollout_percentage != null ? group.rollout_percentage : 100}
                                    min={0}
                                    max={100}
                                    addonAfter="%"
                                />{' '}
                                of <b>{aggregationTargetName}</b> in this set.{' '}
                                {featureFlags[FEATURE_FLAGS.FEATURE_FLAG_ROLLOUT_UX] && (
                                    <>
                                        Will match approximately{' '}
                                        {affectedUsers[index] !== undefined ? (
                                            <b>
                                                {`${
                                                    computeBlastRadiusPercentage(
                                                        group.rollout_percentage,
                                                        index
                                                    ).toPrecision(2) * 1
                                                    // Multiplying by 1 removes trailing zeros after the decimal
                                                    // point added by toPrecision
                                                }% `}
                                            </b>
                                        ) : (
                                            <Spinner className="mr-1" />
                                        )}{' '}
                                        {affectedUsers[index] && affectedUsers[index] >= 0 && totalUsers
                                            ? `(${humanFriendlyNumber(
                                                  Math.floor(
                                                      (affectedUsers[index] * (group.rollout_percentage ?? 100)) / 100
                                                  )
                                              )} / ${humanFriendlyNumber(totalUsers)})`
                                            : ''}{' '}
                                        of total {aggregationTargetName}.
                                    </>
                                )}
                            </div>
                        </div>
                    )}
                    {nonEmptyVariants.length > 0 && (
                        <>
                            <LemonDivider className="my-3" />
                            {readOnly ? (
                                <div>
                                    All <b>{aggregationTargetName}</b> in this set{' '}
                                    {group.variant ? (
                                        <>
                                            {' '}
                                            will be in variant <b>{group.variant}</b>
                                        </>
                                    ) : (
                                        <>have no variant override</>
                                    )}
                                </div>
                            ) : (
                                <div className="feature-flag-form-row">
                                    <div className="centered">
                                        <b>Optional override:</b> Set variant for all <b>{aggregationTargetName}</b> in
                                        this set to{' '}
                                        <LemonSelect
                                            placeholder="Select variant"
                                            allowClear={true}
                                            value={group.variant}
                                            onChange={(value) => updateConditionSet(index, undefined, undefined, value)}
                                            options={nonEmptyVariants.map((variant) => ({
                                                label: variant.key,
                                                value: variant.key,
                                            }))}
                                            data-attr="feature-flags-variant-override-select"
                                        />
                                    </div>
                                </div>
                            )}
                        </>
                    )}
                </div>
            </Col>
        )
    }

    const renderSuperReleaseConditionGroup = (group: FeatureFlagGroupType, index: number): JSX.Element => {
        if (!readOnly) {
            return <></>
        }

        return (
            <Col span={24} md={24} key={`${index}-${_filter_groups.length}`}>
                {index > 0 && <div className="condition-set-separator">OR</div>}
                <div className={clsx('mb-4', 'border', 'rounded', 'p-4', 'FeatureConditionCard--border--highlight')}>
                    <Row align="middle" justify="space-between">
                        <Row align="middle">
                            <div>
                                {group.properties?.length ? (
                                    <>
                                        Match <b>{aggregationTargetName}</b> against value set on{' '}
                                        <span className="simple-tag tag-light-blue text-primary-alt">
                                            {'$feature_enrollment/' + featureFlag.key}
                                        </span>
                                    </>
                                ) : (
                                    <>
                                        Condition set will match <b>all {aggregationTargetName}</b>
                                    </>
                                )}
                            </div>
                        </Row>
                    </Row>
                    <LemonDivider className="my-3" />

                    {group.properties?.length > 0 && (
                        <>
                            <div className="feature-flag-property-display">
                                <LemonButton
                                    icon={<IconSubArrowRight className="arrow-right" />}
                                    status="muted"
                                    size="small"
                                />
                                <span>
                                    If null, default to <b>Release conditions</b>
                                </span>
                            </div>
                            <LemonDivider className="my-3" />
                        </>
                    )}
                    <Row justify="space-between" align="middle">
                        <div />
                        <LemonButton
                            aria-label="more"
                            data-attr={'feature-flag-feature-list-button'}
                            status="primary"
                            size="small"
                            onClick={() =>
                                featureFlag.features &&
                                featureFlag.features.length &&
                                router.actions.push(urls.earlyAccessFeature(featureFlag.features[0].id))
                            }
                        >
                            View Early Access Feature
                        </LemonButton>
                    </Row>
                </div>
            </Col>
        )
    }

    return (
        <>
            <div className="feature-flag-form-row">
                <div data-attr="feature-flag-release-conditions">
                    {readOnly ? (
                        <h3 className="l3">{isSuper ? 'Super Release Conditions' : 'Release conditions'}</h3>
                    ) : (
                        <>
                            <h3 className="l3">Release conditions</h3>
                            <div className="text-muted mb-4">
                                Specify the {aggregationTargetName} to which you want to release this flag. Note that
                                condition sets are rolled out independently of each other.
                            </div>
                        </>
                    )}
                </div>
                {!readOnly && showGroupsOptions && (
                    <div className="centered">
                        Match by
                        <Select
                            value={
                                featureFlag.filters.aggregation_group_type_index != null
                                    ? featureFlag.filters.aggregation_group_type_index
                                    : -1
                            }
                            onChange={(value) => {
                                const groupTypeIndex = value !== -1 ? value : null
                                setAggregationGroupTypeIndex(groupTypeIndex)
                            }}
                            style={{ marginLeft: 8 }}
                            data-attr="feature-flag-aggregation-filter"
                            dropdownMatchSelectWidth={false}
                            dropdownAlign={{
                                // Align this dropdown by the right-hand-side of button
                                points: ['tr', 'br'],
                            }}
                        >
                            <Select.Option key={-1} value={-1}>
                                Users
                            </Select.Option>
                            {groupTypes.map((groupType) => (
                                <Select.Option key={groupType.group_type_index} value={groupType.group_type_index}>
                                    {capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural)}
                                </Select.Option>
                            ))}
                            {matchByGroupsIntroductionOption}
                        </Select>
                    </div>
                )}
            </div>
            <Row className="FeatureConditionCard" gutter={16}>
                {_filter_groups.map((group, index) =>
                    isSuper ? renderSuperReleaseConditionGroup(group, index) : renderReleaseConditionGroup(group, index)
                )}
            </Row>
            {!readOnly && (
                <LemonButton type="secondary" className="mt-0" onClick={addConditionSet} icon={<IconPlus />}>
                    Add condition set
                </LemonButton>
            )}
        </>
    )
}
