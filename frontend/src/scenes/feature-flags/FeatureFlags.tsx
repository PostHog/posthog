import React from 'react'
import { useValues, useActions } from 'kea'
import { featureFlagsLogic } from './featureFlagsLogic'
import { Table, Switch, Typography } from 'antd'
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
import stringWithWBR from 'lib/utils/stringWithWBR'
import { teamLogic } from '../teamLogic'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: FeatureFlags,
    logic: featureFlagsLogic,
}

export function FeatureFlags(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { featureFlags, featureFlagsLoading } = useValues(featureFlagsLogic)
    const { updateFeatureFlag, loadFeatureFlags } = useActions(featureFlagsLogic)
    const { push } = useActions(router)
    const { tableScrollX } = useIsTableScrolling('lg')

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
                        <Typography.Text title={featureFlag.key}>{stringWithWBR(featureFlag.key, 17)}</Typography.Text>
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
                            display: 'flex',
                            wordWrap: 'break-word',
                            maxWidth: 450,
                            width: 'auto',
                            whiteSpace: 'break-spaces',
                        }}
                    >
                        <Typography.Paragraph
                            ellipsis={{
                                rows: 5,
                            }}
                            title={featureFlag.name}
                        >
                            {featureFlag.name}
                        </Typography.Paragraph>
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
                        to={`/insights?events=[{"id":"$pageview","name":"$pageview","type":"events","math":"dau"}]&breakdown_type=event&breakdown=$feature/${featureFlag.key}`}
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
                        <Link to={`/feature_flags/${featureFlag.id}`}>
                            <EditOutlined />
                        </Link>
                        {featureFlag.id && (
                            <DeleteWithUndo
                                endpoint={`projects/${currentTeamId}/feature_flags`}
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
                    to={urls.featureFlag('new')}
                    data-attr="new-feature-flag"
                    icon={<PlusOutlined />}
                >
                    New Feature Flag
                </LinkButton>
            </div>
            <Table
                dataSource={featureFlags}
                columns={columns}
                loading={featureFlagsLoading && featureFlags.length === 0}
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                onRow={(featureFlag) => ({
                    onClick: () => featureFlag.id && push(urls.featureFlag(featureFlag.id)),
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
