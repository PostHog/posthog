import React from 'react'
import { useActions, useValues } from 'kea'
import { featureFlagsLogic, FeatureFlagsTabs } from './featureFlagsLogic'
import { Input, Tabs } from 'antd'
import { Link } from 'lib/components/Link'
import { copyToClipboard, deleteWithUndo } from 'lib/utils'
import { PageHeader } from 'lib/components/PageHeader'
import { FeatureFlagGroupType, FeatureFlagType } from '~/types'
import { normalizeColumnTitle } from 'lib/components/Table/utils'
import { urls } from 'scenes/urls'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { teamLogic } from '../teamLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonDivider } from 'lib/components/LemonDivider'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import { More } from 'lib/components/LemonButton/More'
import { createdAtColumn, createdByColumn } from 'lib/components/LemonTable/columnUtils'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { flagActivityDescriber } from 'scenes/feature-flags/activityDescriptions'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'

export const scene: SceneExport = {
    component: FeatureFlags,
    logic: featureFlagsLogic,
}

function OverViewTab(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { featureFlagsLoading, searchedFeatureFlags, searchTerm } = useValues(featureFlagsLogic)
    const { updateFeatureFlag, loadFeatureFlags, setSearchTerm } = useActions(featureFlagsLogic)

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
                        <Link to={featureFlag.id ? urls.featureFlag(featureFlag.id) : undefined} className="row-name">
                            {stringWithWBR(featureFlag.key, 17)}
                        </Link>
                        {featureFlag.name && <span className="row-description">{featureFlag.name}</span>}
                    </>
                )
            },
        },
        createdByColumn<FeatureFlagType>() as LemonTableColumn<FeatureFlagType, keyof FeatureFlagType | undefined>,
        createdAtColumn<FeatureFlagType>() as LemonTableColumn<FeatureFlagType, keyof FeatureFlagType | undefined>,
        {
            title: 'Rollout',
            width: 200,
            render: function Render(_, featureFlag: FeatureFlagType) {
                return groupFilters(featureFlag.filters.groups)
            },
        },
        {
            title: 'Status',
            dataIndex: 'active',
            sorter: (a: FeatureFlagType, b: FeatureFlagType) => Number(a.active) - Number(b.active),
            width: 100,
            render: function RenderActive(_, featureFlag: FeatureFlagType) {
                return (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <LemonSwitch
                            id={`feature-flag-${featureFlag.id}-switch`}
                            checked={featureFlag.active}
                            onChange={(active) =>
                                featureFlag.id ? updateFeatureFlag({ id: featureFlag.id, payload: { active } }) : null
                            }
                            label={featureFlag.active ? 'Enabled' : 'Disabled'}
                            style={{ fontWeight: 400, padding: 0 }}
                        />
                    </div>
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
                                    type="stealth"
                                    onClick={() => {
                                        copyToClipboard(featureFlag.key, 'feature flag key')
                                    }}
                                    fullWidth
                                >
                                    Copy key
                                </LemonButton>
                                {featureFlag.id && (
                                    <LemonButton type="stealth" to={urls.featureFlag(featureFlag.id)} fullWidth>
                                        Edit
                                    </LemonButton>
                                )}
                                <LemonButton
                                    type="stealth"
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
                                        type="stealth"
                                        style={{ color: 'var(--danger)' }}
                                        onClick={() => {
                                            deleteWithUndo({
                                                endpoint: `projects/${currentTeamId}/feature_flags`,
                                                object: { name: featureFlag.key, id: featureFlag.id },
                                                callback: loadFeatureFlags,
                                            })
                                        }}
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
            <div>
                <Input.Search
                    placeholder="Search for feature flags"
                    allowClear
                    enterButton
                    style={{ maxWidth: 400, width: 'initial', flexGrow: 1, marginBottom: '1rem' }}
                    value={searchTerm}
                    onChange={(e) => {
                        setSearchTerm(e.target.value)
                    }}
                />
            </div>
            <LemonTable
                dataSource={searchedFeatureFlags}
                columns={columns}
                rowKey="key"
                loading={featureFlagsLoading}
                defaultSorting={{ columnKey: 'key', order: 1 }}
                pagination={{ pageSize: 100 }}
                nouns={['feature flag', 'feature flags']}
                data-attr="feature-flag-table"
            />
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

            <Tabs activeKey={activeTab} destroyInactiveTabPane onChange={(t) => setActiveTab(t as FeatureFlagsTabs)}>
                <Tabs.TabPane tab="Overview" key="overview">
                    <OverViewTab />
                </Tabs.TabPane>
                <Tabs.TabPane tab="History" key="history">
                    <ActivityLog scope={ActivityScope.FEATURE_FLAG} describer={flagActivityDescriber} />
                </Tabs.TabPane>
            </Tabs>
        </div>
    )
}

export function groupFilters(groups: FeatureFlagGroupType[]): JSX.Element | string {
    if (groups.length === 0 || !groups.some((group) => group.rollout_percentage !== 0)) {
        // There are no rollout groups or all are at 0%
        return 'No users'
    }
    if (
        groups.some((group) => !group.properties?.length && [null, undefined, 100].includes(group.rollout_percentage))
    ) {
        // There's some group without filters that has 100% rollout
        return 'All users'
    }
    if (groups.length === 1) {
        const { properties, rollout_percentage = null } = groups[0]
        if (properties?.length > 0 && rollout_percentage != null) {
            return (
                <div style={{ display: 'flex', alignItems: 'center' }}>
                    <span style={{ flexShrink: 0, marginRight: 5 }}>{rollout_percentage}% of</span>
                    <PropertyFiltersDisplay filters={properties} style={{ margin: 0, width: '100%' }} />
                </div>
            )
        } else if (properties?.length > 0) {
            return <PropertyFiltersDisplay filters={properties} style={{ margin: 0 }} />
        } else if (rollout_percentage !== null) {
            return `${rollout_percentage}% of all users`
        } else {
            console.error('A group with full rollout was not detected early')
            return 'All users'
        }
    }
    return `${groups.length} groups`
}
