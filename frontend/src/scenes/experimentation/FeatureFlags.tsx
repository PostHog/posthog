import React from 'react'
import { useValues, useActions } from 'kea'
import { featureFlagLogic } from './featureFlagLogic'
import { Table, Switch, Drawer, Button } from 'antd'
//import { EditFeatureFlag } from './EditFeatureFlag'
import { Link } from 'lib/components/Link'
import { DeleteWithUndo } from 'lib/utils'
import { ExportOutlined, PlusOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons'
import { PageHeader } from 'lib/components/PageHeader'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/PropertyFiltersDisplay'
import { createdAtColumn, createdByColumn } from 'lib/components/Table'
import { FeatureFlagGroupType, FeatureFlagType } from '~/types'

export function FeatureFlags(): JSX.Element {
    const { featureFlags, featureFlagsLoading, openedFeatureFlagId } = useValues(featureFlagLogic)
    const { updateFeatureFlag, loadFeatureFlags, setOpenedFeatureFlag } = useActions(featureFlagLogic)

    const columns = [
        {
            title: 'Name',
            dataIndex: 'name',
            className: 'ph-no-capture',
            sorter: (a: FeatureFlagType, b: FeatureFlagType) => ('' + a.name).localeCompare(b.name),
        },
        {
            title: 'Key',
            dataIndex: 'key',
            className: 'ph-no-capture',
            sorter: (a: FeatureFlagType, b: FeatureFlagType) => ('' + a.key).localeCompare(b.key),
        },
        createdAtColumn(),
        createdByColumn(featureFlags),
        {
            title: 'Filters',
            render: function Render(_: string, featureFlag: FeatureFlagType) {
                if (!featureFlag.filters?.groups) {
                    return 'N/A'
                }
                if (featureFlag.filters.groups.length > 1) {
                    return 'Multiple groups'
                }
                return GroupFilters({ group: featureFlag.filters.groups[0] })
            },
        },
        {
            title: 'Active',
            render: function RenderActive(_: string, featureFlag: FeatureFlagType) {
                return (
                    <Switch
                        onClick={(_checked, e) => e.stopPropagation()}
                        checked={featureFlag.active}
                        onChange={(active) => updateFeatureFlag({ ...featureFlag, active })}
                    />
                )
            },
        },
        {
            title: 'Usage',
            render: function Render(_: string, featureFlag: FeatureFlagType) {
                return (
                    <Link
                        to={
                            '/insights?events=[{"id":"$pageview","name":"$pageview","type":"events","math":"dau"}]&properties=[{"key":"$active_feature_flags","operator":"icontains","value":"' +
                            featureFlag.key +
                            '"}]&breakdown_type=event#backTo=Feature Flags&backToURL=' +
                            window.location.pathname
                        }
                        data-attr="usage"
                    >
                        Insights <ExportOutlined />
                    </Link>
                )
            },
        },
        {
            title: 'Actions',
            render: function Render(_: string, featureFlag: FeatureFlagType) {
                return (
                    <>
                        <Button type="link" icon={<EditOutlined />} />
                        <DeleteWithUndo
                            endpoint="feature_flag"
                            object={featureFlag}
                            className="text-danger"
                            style={{ marginLeft: 8 }}
                            callback={loadFeatureFlags}
                        >
                            <DeleteOutlined />
                        </DeleteWithUndo>
                    </>
                )
            },
        },
    ]

    return (
        <div className="feature_flags">
            <PageHeader
                title="Feature Flags"
                caption="Feature flags are a way of turning functionality in your app on or off, based on user properties."
            />
            <div className="mb text-right">
                <Button
                    type="primary"
                    onClick={() => setOpenedFeatureFlag('new')}
                    data-attr="new-feature-flag"
                    icon={<PlusOutlined />}
                >
                    New Feature Flag
                </Button>
            </div>
            <Table
                dataSource={featureFlags}
                columns={columns}
                loading={!featureFlags && featureFlagsLoading}
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                onRow={(featureFlag) => ({
                    onClick: () => setOpenedFeatureFlag(featureFlag.id),
                })}
                size="small"
                rowClassName="cursor-pointer"
                data-attr="feature-flag-table"
            />
            <Drawer
                title={openedFeatureFlagId === 'new' ? 'New feature flag' : 'Feature flag name here'}
                width={500}
                onClose={() => setOpenedFeatureFlag(null)}
                destroyOnClose={true}
                visible={!!openedFeatureFlagId}
            >
                {/* <EditFeatureFlag
                    isNew={openedFeatureFlagId === 'new'}
                    featureFlag={{ rollout_percentage: null, active: true }}
                    logic={logic}
                /> */}
            </Drawer>
        </div>
    )
}

function GroupFilters({ group }: { group: FeatureFlagGroupType }): JSX.Element {
    if (group.properties && group.properties.length > 0 && group.rollout_percentage != null) {
        return (
            <div style={{ display: 'flex', alignItems: 'center' }}>
                <span style={{ flexShrink: 0, marginRight: 5 }}>{group.rollout_percentage}% of</span>
                <PropertyFiltersDisplay filters={group.properties} style={{ margin: 0, width: '100%' }} />
            </div>
        )
    } else if (group.properties && group.properties.length > 0) {
        return <PropertyFiltersDisplay filters={group.properties} style={{ margin: 0 }} />
    } else if (group.rollout_percentage) {
        return `${group.rollout_percentage}% of all users`
    } else {
        return 'N/A'
    }
}
