import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconLock } from '@posthog/icons'
import { LemonDialog, LemonTag, lemonToast } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { FeatureFlagHog } from 'lib/components/hedgehogs'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { createdAtColumn, createdByColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { projectLogic } from 'scenes/projectLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Noun, groupsModel } from '~/models/groupsModel'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ActivityScope,
    AnyPropertyFilter,
    AvailableFeature,
    BaseMathType,
    FeatureFlagEvaluationRuntime,
    FeatureFlagFilters,
    FeatureFlagType,
    ProductKey,
} from '~/types'

import { createMaxToolSurveyConfig } from './FeatureFlag'
import { FeatureFlagEvaluationTags } from './FeatureFlagEvaluationTags'
import { FeatureFlagFiltersSection } from './FeatureFlagFilters'
import { featureFlagLogic } from './featureFlagLogic'
import { FLAGS_PER_PAGE, FeatureFlagsTab, featureFlagsLogic } from './featureFlagsLogic'

// Component for feature flag row actions that needs to use hooks
function FeatureFlagRowActions({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    const { currentProjectId } = useValues(projectLogic)
    const { user } = useValues(userLogic)
    const flagLogic = featureFlagsLogic({})
    const { updateFeatureFlag, loadFeatureFlags } = useActions(flagLogic)

    // Get variants data if it's a multivariate flag
    const multivariateEnabled = Boolean(featureFlag.filters?.multivariate)
    const variants = featureFlag.filters?.multivariate?.variants || []

    // Initialize MaxTool hook for survey creation
    const { openMax } = useMaxTool(createMaxToolSurveyConfig(featureFlag, user, multivariateEnabled, variants))

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
        return urls.insightNew({ query })
    }

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

                    <AccessControlAction
                        resourceType={AccessControlResourceType.FeatureFlag}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={featureFlag.user_access_level}
                    >
                        <LemonButton
                            data-attr={`feature-flag-${featureFlag.key}-switch`}
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
                            fullWidth
                        >
                            {featureFlag.active ? 'Disable' : 'Enable'} feature flag
                        </LemonButton>
                    </AccessControlAction>

                    {featureFlag.id && (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.FeatureFlag}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={featureFlag.user_access_level}
                        >
                            <LemonButton
                                fullWidth
                                disabledReason={
                                    !featureFlag.can_edit
                                        ? "You don't have permission to edit this feature flag."
                                        : null
                                }
                                onClick={() => {
                                    if (featureFlag.id) {
                                        featureFlagLogic({ id: featureFlag.id }).mount()
                                        featureFlagLogic({ id: featureFlag.id }).actions.editFeatureFlag(true)
                                        router.actions.push(urls.featureFlag(featureFlag.id))
                                    }
                                }}
                            >
                                Edit
                            </LemonButton>
                        </AccessControlAction>
                    )}

                    <LemonButton
                        to={urls.featureFlagDuplicate(featureFlag.id)}
                        data-attr="feature-flag-duplicate"
                        fullWidth
                    >
                        Duplicate feature flag
                    </LemonButton>

                    <LemonButton to={tryInInsightsUrl(featureFlag)} data-attr="usage" fullWidth targetBlank>
                        Try out in Insights
                    </LemonButton>

                    {openMax && (
                        <LemonButton onClick={openMax} data-attr="create-survey" fullWidth targetBlank>
                            Create survey
                        </LemonButton>
                    )}

                    <LemonDivider />

                    {featureFlag.id && (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.FeatureFlag}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={featureFlag.user_access_level}
                        >
                            <LemonButton
                                status="danger"
                                onClick={() => {
                                    LemonDialog.open({
                                        title: 'Delete feature flag?',
                                        description: `Are you sure you want to delete "${featureFlag.key}"?`,
                                        primaryButton: {
                                            children: 'Delete',
                                            status: 'danger',
                                            onClick: () => {
                                                void deleteWithUndo({
                                                    endpoint: `projects/${currentProjectId}/feature_flags`,
                                                    object: { name: featureFlag.key, id: featureFlag.id },
                                                    callback: loadFeatureFlags,
                                                }).catch((e) => {
                                                    lemonToast.error(`Failed to delete feature flag: ${e.detail}`)
                                                })
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
                                fullWidth
                            >
                                Delete feature flag
                            </LemonButton>
                        </AccessControlAction>
                    )}
                </>
            }
        />
    )
}

export const scene: SceneExport = {
    component: FeatureFlags,
    logic: featureFlagsLogic,
    settingSectionId: 'environment-feature-flags',
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
    const { aggregationLabel } = useValues(groupsModel)

    const flagLogic = featureFlagsLogic({ flagPrefix })
    const { featureFlagsLoading, featureFlags, count, pagination, filters, shouldShowEmptyState } = useValues(flagLogic)
    const { setFeatureFlagsFilters } = useActions(flagLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { featureFlags: enabledFeatureFlags } = useValues(enabledFeaturesLogic)

    const page = filters.page || 1
    const startCount = (page - 1) * FLAGS_PER_PAGE + 1
    const endCount = page * FLAGS_PER_PAGE < count ? page * FLAGS_PER_PAGE : count

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
                      render: function Render(_, featureFlag: FeatureFlagType) {
                          const tags = featureFlag.tags
                          if (!tags || tags.length === 0) {
                              return null
                          }
                          return enabledFeatureFlags[FEATURE_FLAGS.FLAG_EVALUATION_TAGS] ? (
                              <FeatureFlagEvaluationTags
                                  tags={tags}
                                  evaluationTags={featureFlag.evaluation_tags || []}
                                  staticOnly
                                  flagId={featureFlag.id}
                              />
                          ) : (
                              <ObjectTags tags={tags} staticOnly />
                          )
                      },
                  } as LemonTableColumn<FeatureFlagType, keyof FeatureFlagType | undefined>,
              ]
            : []),
        createdByColumn<FeatureFlagType>() as LemonTableColumn<FeatureFlagType, keyof FeatureFlagType | undefined>,
        createdAtColumn<FeatureFlagType>() as LemonTableColumn<FeatureFlagType, keyof FeatureFlagType | undefined>,
        updatedAtColumn<FeatureFlagType>() as LemonTableColumn<FeatureFlagType, keyof FeatureFlagType | undefined>,
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
                    <div className="flex justify-start gap-1">
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
                        {featureFlag.status === 'STALE' && (
                            <Tooltip
                                title={
                                    <>
                                        <div className="text-sm">Flag at least 30 days old and fully rolled out</div>
                                        <div className="text-xs">
                                            Make sure to remove any references to this flag in your code before deleting
                                            it.
                                        </div>
                                    </>
                                }
                                placement="left"
                            >
                                <span>
                                    <LemonTag type="warning" className="uppercase cursor-default">
                                        Stale
                                    </LemonTag>
                                </span>
                            </Tooltip>
                        )}
                    </div>
                )
            },
        },
        ...(enabledFeaturesLogic.values.featureFlags?.[FEATURE_FLAGS.FLAG_EVALUATION_RUNTIMES]
            ? [
                  {
                      title: 'Runtime',
                      dataIndex: 'evaluation_runtime' as keyof FeatureFlagType,
                      width: 120,
                      render: function RenderFlagRuntime(_: any, featureFlag: FeatureFlagType) {
                          const runtime = featureFlag.evaluation_runtime || FeatureFlagEvaluationRuntime.ALL
                          return (
                              <LemonTag type="default" className="uppercase">
                                  {runtime === FeatureFlagEvaluationRuntime.ALL
                                      ? 'All'
                                      : runtime === FeatureFlagEvaluationRuntime.CLIENT
                                        ? 'Client'
                                        : runtime === FeatureFlagEvaluationRuntime.SERVER
                                          ? 'Server'
                                          : 'All'}
                              </LemonTag>
                          )
                      },
                  },
              ]
            : []),
        {
            width: 0,
            render: function Render(_, featureFlag: FeatureFlagType) {
                return <FeatureFlagRowActions featureFlag={featureFlag} />
            },
        },
    ]

    const filtersSection = (
        <FeatureFlagFiltersSection
            filters={filters}
            setFeatureFlagsFilters={setFeatureFlagsFilters}
            searchPlaceholder={searchPlaceholder || ''}
            filtersConfig={{
                search: true,
                type: true,
                status: true,
                createdBy: true,
                tags: true,
                runtime: true,
            }}
        />
    )

    return (
        <SceneContent>
            <ProductIntroduction
                productName="Feature flags"
                productKey={ProductKey.FEATURE_FLAGS}
                thingName="feature flag"
                description="Use feature flags to safely deploy and roll back new features in an easy-to-manage way. Roll variants out to certain groups, a percentage of users, or everyone all at once."
                docsURL="https://posthog.com/docs/feature-flags/manual"
                action={() => router.actions.push(urls.featureFlag('new'))}
                isEmpty={shouldShowEmptyState}
                customHog={FeatureFlagHog}
                className={cn('my-0')}
            />
            <div>{filtersSection}</div>
            <LemonDivider className="my-0" />
            <div>
                <span className="text-secondary">
                    {featureFlagsLoading ? (
                        <WrappingLoadingSkeleton>1-100 of 150 flags</WrappingLoadingSkeleton>
                    ) : count ? (
                        `${startCount}${endCount - startCount > 1 ? '-' + endCount : ''} of ${count} flag${
                            count === 1 ? '' : 's'
                        }`
                    ) : null}
                </span>
            </div>

            <LemonTable
                dataSource={featureFlags.results}
                columns={columns}
                rowKey="key"
                defaultSorting={{
                    columnKey: 'created_at',
                    order: -1,
                }}
                noSortingCancellation
                loading={featureFlagsLoading}
                pagination={pagination}
                nouns={nouns}
                data-attr="feature-flag-table"
                emptyState="No results for this filter, change filter or create a new flag."
                onSort={(newSorting) =>
                    setFeatureFlagsFilters({
                        order: newSorting ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}` : undefined,
                        page: 1,
                    })
                }
            />
        </SceneContent>
    )
}

export function FeatureFlags(): JSX.Element {
    const { activeTab } = useValues(featureFlagsLogic)
    const { setActiveTab } = useActions(featureFlagsLogic)
    return (
        <SceneContent className="feature_flags">
            <SceneTitleSection
                name="Feature flags"
                resourceType={{
                    type: 'feature_flag',
                }}
                actions={
                    <AccessControlAction
                        resourceType={AccessControlResourceType.FeatureFlag}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            type="primary"
                            to={urls.featureFlag('new')}
                            data-attr="new-feature-flag"
                            size="small"
                        >
                            New feature flag
                        </LemonButton>
                    </AccessControlAction>
                }
            />
            <SceneDivider />
            <LemonTabs
                activeKey={activeTab}
                onChange={(newKey) => setActiveTab(newKey)}
                sceneInset
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
                data-attr="feature-flags-tab-navigation"
            />
        </SceneContent>
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
