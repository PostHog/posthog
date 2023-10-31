import { useActions, useValues } from 'kea'
import { featureFlagsLogic, FeatureFlagsTab } from './featureFlagsLogic'
import { Link } from 'lib/lemon-ui/Link'
import { copyToClipboard, deleteWithUndo } from 'lib/utils'
import { PageHeader } from 'lib/components/PageHeader'
import { AnyPropertyFilter, AvailableFeature, FeatureFlagFilters, FeatureFlagType, ProductKey } from '~/types'
import { normalizeColumnTitle } from 'lib/components/Table/utils'
import { urls } from 'scenes/urls'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { teamLogic } from '../teamLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { LemonInput, LemonSelect, LemonTag } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconLock } from 'lib/lemon-ui/icons'
import { router } from 'kea-router'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { userLogic } from 'scenes/userLogic'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagHog } from 'lib/components/hedgehogs'
import { Noun, groupsModel } from '~/models/groupsModel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

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
    const { featureFlagsLoading, searchedFeatureFlags, searchTerm, uniqueCreators, filters, shouldShowEmptyState } =
        useValues(flagLogic)
    const { updateFeatureFlag, loadFeatureFlags, setSearchTerm, setFeatureFlagsFilters } = useActions(flagLogic)
    const { user, hasAvailableFeature } = useValues(userLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const shouldShowProductIntroduction =
        !user?.has_seen_product_intro_for?.[ProductKey.FEATURE_FLAGS] &&
        !!featureFlags[FEATURE_FLAGS.SHOW_PRODUCT_INTRO_EXISTING_PRODUCTS]

    const columns: LemonTableColumns<FeatureFlagType> = [
        {
            title: normalizeColumnTitle('Key'),
            dataIndex: 'key',
            className: 'ph-no-capture',
            sticky: true,
            width: '40%',
            sorter: (a: FeatureFlagType, b: FeatureFlagType) => (a.key || '').localeCompare(b.key || ''),
            render: function Render(_, featureFlag: FeatureFlagType) {
                return (
                    <>
                        <div className="flex flex-row items-center">
                            <Link
                                to={featureFlag.id ? urls.featureFlag(featureFlag.id) : undefined}
                                className="row-name"
                            >
                                {stringWithWBR(featureFlag.key, 17)}
                            </Link>
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
                        </div>

                        {featureFlag.name && (
                            <LemonMarkdown className="row-description" lowKeyHeadings>
                                {featureFlag.name}
                            </LemonMarkdown>
                        )}
                    </>
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
                                    status="stealth"
                                    onClick={async () => {
                                        await copyToClipboard(featureFlag.key, 'feature flag key')
                                    }}
                                    fullWidth
                                >
                                    Copy feature flag key
                                </LemonButton>
                                <LemonButton
                                    status="stealth"
                                    onClick={() => {
                                        featureFlag.id
                                            ? updateFeatureFlag({
                                                  id: featureFlag.id,
                                                  payload: { active: !featureFlag.active },
                                              })
                                            : null
                                    }}
                                    id={`feature-flag-${featureFlag.id}-switch`}
                                    disabled={!featureFlag.can_edit}
                                    fullWidth
                                >
                                    {featureFlag.active ? 'Disable' : 'Enable'} feature flag
                                </LemonButton>
                                {featureFlag.id && (
                                    <LemonButton
                                        status="stealth"
                                        fullWidth
                                        disabled={!featureFlag.can_edit}
                                        onClick={() =>
                                            featureFlag.id && router.actions.push(urls.featureFlag(featureFlag.id))
                                        }
                                    >
                                        Edit
                                    </LemonButton>
                                )}
                                <LemonButton
                                    status="stealth"
                                    to={urls.insightNew({
                                        events: [{ id: '$pageview', name: '$pageview', type: 'events', math: 'dau' }],
                                        breakdown_type: 'event',
                                        breakdown: `$feature/${featureFlag.key}`,
                                    })}
                                    data-attr="usage"
                                    fullWidth
                                >
                                    Try out in Insights
                                </LemonButton>
                                <LemonDivider />
                                {featureFlag.id && (
                                    <LemonButton
                                        status="danger"
                                        onClick={() => {
                                            deleteWithUndo({
                                                endpoint: `projects/${currentTeamId}/feature_flags`,
                                                object: { name: featureFlag.key, id: featureFlag.id },
                                                callback: loadFeatureFlags,
                                            })
                                        }}
                                        disabled={!featureFlag.can_edit}
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
            {(shouldShowEmptyState || shouldShowProductIntroduction) && (
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
            )}{' '}
            {!shouldShowEmptyState && (
                <>
                    <div>
                        <div className="flex justify-between mb-4">
                            <LemonInput
                                type="search"
                                placeholder={searchPlaceholder || ''}
                                onChange={setSearchTerm}
                                value={searchTerm || ''}
                            />
                            <div className="flex items-center gap-2">
                                {hasAvailableFeature(AvailableFeature.MULTIVARIATE_FLAGS) && (
                                    <>
                                        <span>
                                            <b>Type</b>
                                        </span>
                                        <LemonSelect
                                            dropdownMatchSelectWidth={false}
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
                                    </>
                                )}
                                <span>
                                    <b>Status</b>
                                </span>
                                <LemonSelect
                                    dropdownMatchSelectWidth={false}
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
                                <LemonSelect
                                    dropdownMatchSelectWidth={false}
                                    onChange={(user) => {
                                        if (user) {
                                            if (user === 'any') {
                                                if (filters) {
                                                    const { created_by, ...restFilters } = filters
                                                    setFeatureFlagsFilters(restFilters, true)
                                                }
                                            } else {
                                                setFeatureFlagsFilters({ created_by: user })
                                            }
                                        }
                                    }}
                                    options={uniqueCreators}
                                    value={filters.created_by ?? 'any'}
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
                title="Feature Flags"
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
                    <PropertyFiltersDisplay
                        filters={properties as AnyPropertyFilter[]}
                        style={{ margin: 0, flexDirection: 'column' }}
                    />
                </div>
            )
        } else if (rollout_percentage !== null) {
            return `${rollout_percentage}% of all ${aggregationTargetName}`
        } else {
            console.error('A group with full rollout was not detected early')
            return `100% of all ${aggregationTargetName}`
        }
    }
    return 'Multiple groups'
}
