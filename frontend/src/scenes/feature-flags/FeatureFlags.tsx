import { IconLock } from '@posthog/icons'
import { LemonDialog, LemonInput, LemonSelect, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { FeatureFlagHog } from 'lib/components/hedgehogs'
import { MemberSelect } from 'lib/components/MemberSelect'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { groupsModel, Noun } from '~/models/groupsModel'
import { InsightVizNode, NodeKind } from '~/queries/schema'
import {
    ActivityScope,
    AnyPropertyFilter,
    AvailableFeature,
    BaseMathType,
    FeatureFlagFilters,
    FeatureFlagType,
    ProductKey,
} from '~/types'

import { teamLogic } from '../teamLogic'
import { featureFlagsLogic, FeatureFlagsTab } from './featureFlagsLogic'

export const scene: SceneExport = {
    component: FeatureFlags,
    logic: featureFlagsLogic,
}

export function OverViewTab({
    flagPrefix = '',
    searchPlaceholder = 'Search for feature flags',
    nouns = ['feature flag', 'feature flags'],
}: {
    flagPrefix?: string
    searchPlaceholder?: string
    nouns?: [string, string]
}): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { aggregationLabel } = useValues(groupsModel)

    const flagLogic = featureFlagsLogic({ flagPrefix })
    const { featureFlagsLoading, searchedFeatureFlags, searchTerm, filters, shouldShowEmptyState } =
        useValues(flagLogic)
    const { updateFeatureFlag, loadFeatureFlags, setSearchTerm, setFeatureFlagsFilters } = useActions(flagLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    const tryInInsightsUrl = (featureFlag: FeatureFlagType): string => {
        const query: InsightVizNode = {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        event: '$pageview',
                        name: '$pageview',
                        kind: NodeKind.EventsNode,
                        math: BaseMathType.UniqueUsers,
                    },
                ],
                breakdownFilter: {
                    breakdown_type: 'event',
                    breakdown: `$feature/${featureFlag.key}`,
                },
            },
        }
        return urls.insightNew(undefined, undefined, query)
    }

    const columns: LemonTableColumns<FeatureFlagType> = [
        {
            title: 'Key',
            dataIndex: 'key',
            className: 'ph-no-capture',
            sticky: true,
            width: '40%',
            sorter: (a: FeatureFlagType, b: FeatureFlagType) => (a.key || '').localeCompare(b.key || ''),
            render: function Render(_, featureFlag: FeatureFlagType) {
                return (
                    <LemonTableLink
                        to={featureFlag.id ? urls.featureFlag(featureFlag.id) : undefined}
                        title={
                            <>
                                <span>{stringWithWBR(featureFlag.key, 17)}</span>
                                {!featureFlag.can_edit && (
                                    <Tooltip title="You don't have edit permissions for this feature flag.">
                                        <IconLock
                                            style={{
                                                marginLeft: 6,
                                                verticalAlign: '-0.125em',
                                                display: 'inline',
                                            }}
                                        />
                                    </Tooltip>
                                )}
                            </>
                        }
                        description={featureFlag.name}
                    />
                )
            },
        },
        ...(hasAvailableFeature(AvailableFeature.TAGGING)
            ? [
                  {
                      title: 'Tags',
                      dataIndex: 'tags' as keyof FeatureFlagType,
                      render: function Render(tags: FeatureFlagType['tags']) {
                          return tags ? <ObjectTags tags={tags} staticOnly /> : null
                      },
                  } as LemonTableColumn<FeatureFlagType, keyof FeatureFlagType | undefined>,
              ]
            : []),
        createdByColumn<FeatureFlagType>() as LemonTableColumn<FeatureFlagType, keyof FeatureFlagType | undefined>,
        createdAtColumn<FeatureFlagType>() as LemonTableColumn<FeatureFlagType, keyof FeatureFlagType | undefined>,
        {
            title: 'Release conditions',
            width: 100,
            render: function Render(_, featureFlag: FeatureFlagType) {
                const releaseText = groupFilters(featureFlag.filters, undefined, aggregationLabel)
                return typeof releaseText === 'string' && releaseText.startsWith('100% of') ? (
                    <LemonTag type="highlight">{releaseText}</LemonTag>
                ) : (
                    releaseText
                )
            },
        },
        {
            title: 'Status',
            dataIndex: 'active',
            sorter: (a: FeatureFlagType, b: FeatureFlagType) => Number(a.active) - Number(b.active),
            width: 100,
            render: function RenderActive(_, featureFlag: FeatureFlagType) {
                return (
                    <>
                        {featureFlag.performed_rollback ? (
                            <LemonTag type="warning" className="uppercase">
                                Rolled Back
                            </LemonTag>
                        ) : featureFlag.active ? (
                            <LemonTag type="success" className="uppercase">
                                Enabled
                            </LemonTag>
                        ) : (
                            <LemonTag type="default" className="uppercase">
                                Disabled
                            </LemonTag>
                        )}
                    </>
                )
            },
        },
        {
            width: 0,
            render: function Render(_, featureFlag: FeatureFlagType) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    onClick={() => {
                                        void copyToClipboard(featureFlag.key, 'feature flag key')
                                    }}
                                    fullWidth
                                >
                                    Copy feature flag key
                                </LemonButton>
                                <LemonButton
                                    onClick={() => {
                                        const newValue = !featureFlag.active
                                        LemonDialog.open({
                                            title: `${newValue === true ? 'Enable' : 'Disable'} this flag?`,
                                            description: `This flag will be immediately ${
                                                newValue === true ? 'rolled out to' : 'rolled back from'
                                            } the users matching the release conditions.`,
                                            primaryButton: {
                                                children: 'Confirm',
                                                type: 'primary',
                                                onClick: () => {
                                                    featureFlag.id
                                                        ? updateFeatureFlag({
                                                              id: featureFlag.id,
                                                              payload: { active: newValue },
                                                          })
                                                        : null
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
                                    id={`feature-flag-${featureFlag.id}-switch`}
                                    disabled={!featureFlag.can_edit}
                                    fullWidth
                                >
                                    {featureFlag.active ? 'Disable' : 'Enable'} feature flag
                                </LemonButton>
                                {featureFlag.id && (
                                    <LemonButton
                                        fullWidth
                                        disabled={!featureFlag.can_edit}
                                        onClick={() =>
                                            featureFlag.id && router.actions.push(urls.featureFlag(featureFlag.id))
                                        }
                                    >
                                        Edit
                                    </LemonButton>
                                )}
                                <LemonButton to={tryInInsightsUrl(featureFlag)} data-attr="usage" fullWidth>
                                    Try out in Insights
                                </LemonButton>
                                <LemonDivider />
                                {featureFlag.id && (
                                    <LemonButton
                                        status="danger"
                                        onClick={() => {
                                            void deleteWithUndo({
                                                endpoint: `projects/${currentTeamId}/feature_flags`,
                                                object: { name: featureFlag.key, id: featureFlag.id },
                                                callback: loadFeatureFlags,
                                            })
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
                                        fullWidth
                                    >
                                        Delete feature flag
                                    </LemonButton>
                                )}
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <>
            <ProductIntroduction
                productName="Feature flags"
                productKey={ProductKey.FEATURE_FLAGS}
                thingName="feature flag"
                description="Use feature flags to safely deploy and roll back new features in an easy-to-manage way. Roll variants out to certain groups, a percentage of users, or everyone all at once."
                docsURL="https://posthog.com/docs/feature-flags/manual"
                action={() => router.actions.push(urls.featureFlag('new'))}
                isEmpty={shouldShowEmptyState}
                customHog={FeatureFlagHog}
            />
            {!shouldShowEmptyState && (
                <>
                    <div>
                        <div className="flex justify-between mb-4 gap-2 flex-wrap">
                            <LemonInput
                                className="w-60"
                                type="search"
                                placeholder={searchPlaceholder || ''}
                                onChange={setSearchTerm}
                                value={searchTerm || ''}
                            />
                            <div className="flex items-center gap-2">
                                <span>
                                    <b>Type</b>
                                </span>
                                <LemonSelect
                                    dropdownMatchSelectWidth={false}
                                    size="small"
                                    onChange={(type) => {
                                        if (type) {
                                            if (type === 'all') {
                                                if (filters) {
                                                    const { type, ...restFilters } = filters
                                                    setFeatureFlagsFilters(restFilters, true)
                                                }
                                            } else {
                                                setFeatureFlagsFilters({ type })
                                            }
                                        }
                                    }}
                                    options={[
                                        { label: 'All', value: 'all' },
                                        { label: 'Boolean', value: 'boolean' },
                                        { label: 'Multiple variants', value: 'multivariant' },
                                        { label: 'Experiment', value: 'experiment' },
                                    ]}
                                    value={filters.type ?? 'all'}
                                />
                                <span>
                                    <b>Status</b>
                                </span>
                                <LemonSelect
                                    dropdownMatchSelectWidth={false}
                                    size="small"
                                    onChange={(status) => {
                                        if (status) {
                                            if (status === 'all') {
                                                if (filters) {
                                                    const { active, ...restFilters } = filters
                                                    setFeatureFlagsFilters(restFilters, true)
                                                }
                                            } else {
                                                setFeatureFlagsFilters({ active: status })
                                            }
                                        }
                                    }}
                                    options={[
                                        { label: 'All', value: 'all' },
                                        { label: 'Enabled', value: 'true' },
                                        { label: 'Disabled', value: 'false' },
                                    ]}
                                    value={filters.active ?? 'all'}
                                />
                                <span className="ml-1">
                                    <b>Created by</b>
                                </span>
                                <MemberSelect
                                    defaultLabel="Any user"
                                    value={filters.created_by ?? null}
                                    onChange={(user) => {
                                        if (!user) {
                                            if (filters) {
                                                const { created_by, ...restFilters } = filters
                                                setFeatureFlagsFilters(restFilters, true)
                                            }
                                        } else {
                                            setFeatureFlagsFilters({ created_by: user.id })
                                        }
                                    }}
                                />
                            </div>
                        </div>
                    </div>
                    <LemonTable
                        dataSource={searchedFeatureFlags}
                        columns={columns}
                        rowKey="key"
                        defaultSorting={{
                            columnKey: 'created_at',
                            order: -1,
                        }}
                        noSortingCancellation
                        loading={featureFlagsLoading}
                        pagination={{ pageSize: 100 }}
                        nouns={nouns}
                        data-attr="feature-flag-table"
                        emptyState="No results for this filter, change filter or create a new flag."
                    />
                </>
            )}
        </>
    )
}

export function FeatureFlags(): JSX.Element {
    const { activeTab } = useValues(featureFlagsLogic)
    const { setActiveTab } = useActions(featureFlagsLogic)

    return (
        <div className="feature_flags">
            <PageHeader
                buttons={
                    <LemonButton type="primary" to={urls.featureFlag('new')} data-attr="new-feature-flag">
                        New feature flag
                    </LemonButton>
                }
            />
            <LemonTabs
                activeKey={activeTab}
                onChange={(newKey) => setActiveTab(newKey)}
                tabs={[
                    {
                        key: FeatureFlagsTab.OVERVIEW,
                        label: 'Overview',
                        content: <OverViewTab />,
                    },
                    {
                        key: FeatureFlagsTab.HISTORY,
                        label: 'History',
                        content: <ActivityLog scope={ActivityScope.FEATURE_FLAG} />,
                    },
                ]}
            />
        </div>
    )
}

export function groupFilters(
    filters: FeatureFlagFilters,
    stringOnly?: true,
    aggregationLabel?: (groupTypeIndex: number | null | undefined, deferToUserWording?: boolean) => Noun
): string
export function groupFilters(
    filters: FeatureFlagFilters,
    stringOnly?: false,
    aggregationLabel?: (groupTypeIndex: number | null | undefined, deferToUserWording?: boolean) => Noun
): JSX.Element | string
export function groupFilters(
    filters: FeatureFlagFilters,
    stringOnly?: boolean,
    aggregationLabel?: (groupTypeIndex: number | null | undefined, deferToUserWording?: boolean) => Noun
): JSX.Element | string {
    const aggregationTargetName =
        aggregationLabel && filters.aggregation_group_type_index != null
            ? aggregationLabel(filters.aggregation_group_type_index).plural
            : 'users'
    const groups = filters.groups || []

    if (groups.length === 0 || !groups.some((group) => group.rollout_percentage !== 0)) {
        // There are no rollout groups or all are at 0%
        return `No ${aggregationTargetName}`
    }
    if (
        groups.some((group) => !group.properties?.length && [null, undefined, 100].includes(group.rollout_percentage))
    ) {
        // There's some group without filters that has 100% rollout
        return `100% of all ${aggregationTargetName}`
    }

    if (groups.length === 1) {
        const { properties, rollout_percentage = null } = groups[0]
        if ((properties?.length || 0) > 0) {
            return stringOnly ? (
                `${rollout_percentage ?? 100}% of one group`
            ) : (
                <div className="flex items-center">
                    <span className="shrink-0 mr-2">{rollout_percentage ?? 100}% of</span>
                    <PropertyFiltersDisplay filters={properties as AnyPropertyFilter[]} />
                </div>
            )
        } else if (rollout_percentage !== null) {
            return `${rollout_percentage}% of all ${aggregationTargetName}`
        }
        console.error('A group with full rollout was not detected early')
        return `100% of all ${aggregationTargetName}`
    }
    return 'Multiple groups'
}
