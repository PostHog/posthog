import React, { Fragment, useState } from 'react'
import { hot } from 'react-hot-loader/root'
import { useValues, useActions } from 'kea'
import { featureFlagLogic } from './featureFlagLogic'
import { Table, Switch, Drawer, Button } from 'antd'
import { EditFeatureFlag } from './EditFeatureFlag'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'
import { Link } from 'lib/components/Link'
import { DeleteWithUndo } from 'lib/utils'
import { ExportOutlined, PlusOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons'
import { PageHeader } from 'lib/components/PageHeader'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/PropertyFiltersDisplay'
import { createdAtColumn, createdByColumn } from 'lib/components/Table'

export const FeatureFlags = hot(_FeatureFlags)
function _FeatureFlags() {
    const [openFeatureFlag, setOpenFeatureFlag] = useState(false)
    const logic = featureFlagLogic({ closeDrawer: () => setOpenFeatureFlag(false) })
    const { featureFlags, featureFlagsLoading } = useValues(logic)
    const { updateFeatureFlag, loadFeatureFlags } = useActions(logic)

    let columns = [
        {
            title: 'Name',
            dataIndex: 'name',
            sorter: (a, b) => ('' + a.name).localeCompare(b.name),
        },
        {
            title: 'Key',
            dataIndex: 'key',
            sorter: (a, b) => ('' + a.key).localeCompare(b.key),
        },
        createdAtColumn(),
        createdByColumn(featureFlags),
        {
            title: 'Filters',
            render: function RenderGroups(featureFlag) {
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
            render: function RenderActive(featureFlag) {
                return (
                    <Switch
                        onClick={(_, e) => e.stopPropagation()}
                        checked={featureFlag.active}
                        onChange={(active) => updateFeatureFlag({ ...featureFlag, active })}
                    />
                )
            },
        },
        {
            title: 'Usage',
            render: function RenderUsage(featureFlag) {
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
            render: function RenderActive(featureFlag) {
                return (
                    <>
                        <Link>
                            <EditOutlined onClick={() => setOpenFeatureFlag(featureFlag)} />
                        </Link>
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
                    onClick={() => setOpenFeatureFlag('new')}
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
                    onClick: () => setOpenFeatureFlag(featureFlag),
                })}
                size="small"
                rowClassName={'cursor-pointer ' + rrwebBlockClass}
                data-attr="feature-flag-table"
            />
            <Drawer
                title={openFeatureFlag === 'new' ? 'New feature flag' : openFeatureFlag.name}
                width={500}
                onClose={() => setOpenFeatureFlag(false)}
                destroyOnClose={true}
                visible={openFeatureFlag}
            >
                {openFeatureFlag === 'new' ? (
                    <EditFeatureFlag
                        isNew={true}
                        featureFlag={{ rollout_percentage: null, active: true }}
                        logic={logic}
                    />
                ) : (
                    <EditFeatureFlag featureFlag={openFeatureFlag} logic={logic} />
                )}
            </Drawer>
        </div>
    )
}

function GroupFilters({ group }) {
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
