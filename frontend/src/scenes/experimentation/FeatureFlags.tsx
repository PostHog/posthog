import React from 'react'
import { useValues, useActions } from 'kea'
import { featureFlagsLogic } from './featureFlagsLogic'
import { Table, Switch } from 'antd'
import { Link } from 'lib/components/Link'
import { DeleteWithUndo } from 'lib/utils'
import { ExportOutlined, PlusOutlined, DeleteOutlined, EditOutlined, DisconnectOutlined } from '@ant-design/icons'
import { PageHeader } from 'lib/components/PageHeader'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { createdAtColumn, createdByColumn } from 'lib/components/Table/Table'
import { FeatureFlagGroupType, FeatureFlagType } from '~/types'
import { router } from 'kea-router'
import { LinkButton } from 'lib/components/LinkButton'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { normalizeColumnTitle, useIsTableScrolling } from 'lib/components/Table/utils'
import { urls } from 'scenes/urls'
import { Tooltip } from 'lib/components/Tooltip'

export function FeatureFlags(): JSX.Element {
    const { featureFlags, featureFlagsLoading } = useValues(featureFlagsLogic)
    const { updateFeatureFlag, loadFeatureFlags } = useActions(featureFlagsLogic)
    const { push } = useActions(router)
    const { tableScrollX } = useIsTableScrolling('lg')

    const BackTo = '#backTo=Feature Flags&backToURL=/feature_flags'

    const columns = [
        {
            title: normalizeColumnTitle('Key'),
            dataIndex: 'key',
            className: 'ph-no-capture',
            fixed: 'left',
            width: '15%',
            sorter: (a: FeatureFlagType, b: FeatureFlagType) => ('' + a.key).localeCompare(b.key),
            render: function Render(_: string, featureFlag: FeatureFlagType) {
                return (
                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            maxWidth: 210,
                            width: 'auto',
                        }}
                    >
                        {!featureFlag.active && (
                            <Tooltip title="This feature flag is disabled.">
                                <DisconnectOutlined style={{ marginRight: 4 }} />
                            </Tooltip>
                        )}
                        <div onClick={(e) => e.stopPropagation()}>
                            <CopyToClipboardInline
                                iconStyle={{ color: 'var(--primary)' }}
                                iconPosition="start"
                                explicitValue={featureFlag.key}
                            />
                        </div>
                        <span style={{ marginRight: 4 }}>{featureFlag.key}</span>
                    </div>
                )
            },
        },
        {
            title: normalizeColumnTitle('Description'),
            render: function Render(_: string, featureFlag: FeatureFlagType) {
                return (
                    <div
                        style={{
                            wordWrap: 'break-word',
                            maxWidth: 450,
                            width: 'auto',
                            whiteSpace: 'break-spaces',
                        }}
                    >
                        {featureFlag.name}
                    </div>
                )
            },
            className: 'ph-no-capture',
            sorter: (a: FeatureFlagType, b: FeatureFlagType) => ('' + a.name).localeCompare(b.name),
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
            title: 'Enabled',
            width: 90,
            align: 'right',
            render: function RenderActive(_: string, featureFlag: FeatureFlagType) {
                return (
                    <Switch
                        onClick={(_checked, e) => e.stopPropagation()}
                        checked={featureFlag.active}
                        onChange={(active) =>
                            featureFlag.id ? updateFeatureFlag({ id: featureFlag.id, payload: { active } }) : null
                        }
                    />
                )
            },
        },
        {
            title: normalizeColumnTitle('Usage'),
            width: 100,
            align: 'right',
            render: function Render(_: string, featureFlag: FeatureFlagType) {
                return (
                    <Link
                        to={
                            '/insights?events=[{"id":"$pageview","name":"$pageview","type":"events","math":"dau"}]&properties=[{"key":"$active_feature_flags","operator":"icontains","value":"' +
                            featureFlag.key +
                            '"}]&breakdown_type=event' +
                            BackTo
                        }
                        data-attr="usage"
                        onClick={(e) => e.stopPropagation()}
                    >
                        Insights <ExportOutlined />
                    </Link>
                )
            },
        },
        {
            title: normalizeColumnTitle('Actions'),
            width: 100,
            align: 'right',
            render: function Render(_: string, featureFlag: FeatureFlagType) {
                return (
                    <>
                        <Link to={`/feature_flags/${featureFlag.id}${BackTo}`}>
                            <EditOutlined />
                        </Link>
                        {featureFlag.id && (
                            <DeleteWithUndo
                                endpoint="feature_flag"
                                object={{ name: featureFlag.name, id: featureFlag.id }}
                                className="text-danger"
                                style={{ marginLeft: 8 }}
                                callback={loadFeatureFlags}
                            >
                                <DeleteOutlined />
                            </DeleteWithUndo>
                        )}
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
                <LinkButton
                    type="primary"
                    to={[urls.featureFlag('new'), {}, BackTo]}
                    data-attr="new-feature-flag"
                    icon={<PlusOutlined />}
                >
                    New Feature Flag
                </LinkButton>
            </div>
            <Table
                dataSource={featureFlags}
                columns={columns}
                loading={!featureFlags && featureFlagsLoading}
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                onRow={(featureFlag) => ({
                    onClick: () => featureFlag.id && push(urls.featureFlag(featureFlag.id), {}, BackTo),
                    style: !featureFlag.active ? { color: 'var(--muted)' } : {},
                })}
                size="small"
                rowClassName="cursor-pointer"
                data-attr="feature-flag-table"
                scroll={{ x: tableScrollX }}
            />
        </div>
    )
}

function GroupFilters({ group }: { group: FeatureFlagGroupType }): JSX.Element | string {
    if (group.properties && group.properties.length > 0 && group.rollout_percentage != null) {
        return (
            <div style={{ display: 'flex', alignItems: 'center' }}>
                <span style={{ flexShrink: 0, marginRight: 5 }}>{group.rollout_percentage}% of</span>
                <PropertyFiltersDisplay filters={group.properties} style={{ margin: 0, width: '100%' }} />
            </div>
        )
    } else if (group.properties && group.properties.length > 0) {
        return <PropertyFiltersDisplay filters={group.properties} style={{ margin: 0 }} />
    } else if (group.rollout_percentage !== null && group.rollout_percentage !== undefined) {
        return `${group.rollout_percentage}% of all users`
    } else {
        return '100% of all users'
    }
}
