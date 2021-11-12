import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { featureFlagsLogic } from './featureFlagsLogic'
import { Switch, Typography, Input } from 'antd'
import { Link } from 'lib/components/Link'
import { deleteWithUndo } from 'lib/utils'
import { ExportOutlined, PlusOutlined, DisconnectOutlined } from '@ant-design/icons'
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
import { LemonTable, LemonTableColumns } from '../../lib/components/LemonTable/LemonTable'
import { LemonButton } from '../../lib/components/LemonButton'
import { IconEllipsis } from '../../lib/components/icons'
import { LemonSpacer } from '../../lib/components/LemonRow'
import { LemonSwitch } from '../../lib/components/LemonSwitch/LemonSwitch'

export const scene: SceneExport = {
    component: FeatureFlags,
    logic: featureFlagsLogic,
}

export function FeatureFlags(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    // eslint-disable-next-line no-unused-vars, @typescript-eslint/no-unused-vars
    const { featureFlags, featureFlagsLoading, searchedFeatureFlags, searchTerm } = useValues(featureFlagsLogic)
    const { updateFeatureFlag, loadFeatureFlags, setSearchTerm } = useActions(featureFlagsLogic)
    const { push } = useActions(router)
    // eslint-disable-next-line no-unused-vars, @typescript-eslint/no-unused-vars
    const { tableScrollX } = useIsTableScrolling('lg')

    const columns: LemonTableColumns<FeatureFlagType> = [
        {
            title: normalizeColumnTitle('Key'),
            dataIndex: 'key',
            className: 'ph-no-capture',
            sticky: true,
            width: '15%',
            sorter: (a: FeatureFlagType, b: FeatureFlagType) => ('' + a.key).localeCompare(b.key),
            render: function Render(_, featureFlag: FeatureFlagType) {
                return (
                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            maxWidth: 210,
                            width: 'auto',
                        }}
                    >
                        <CopyToClipboardInline explicitValue={featureFlag.key}>
                            <strong>{stringWithWBR(featureFlag.key, 17)}</strong>
                        </CopyToClipboardInline>
                    </div>
                )
            },
        },
        {
            title: normalizeColumnTitle('Description'),
            render: function Render(_, featureFlag: FeatureFlagType) {
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
            title: 'Release conditions',
            render: function Render(_, featureFlag: FeatureFlagType) {
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
            title: 'Status',
            width: 90,
            align: 'right',
            render: function RenderActive(_, featureFlag: FeatureFlagType) {
                const switchId = `feature-flag-${featureFlag.id}-switch`
                return (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'end' }}>
                        <label htmlFor={switchId}>{featureFlag.active ? 'Enabled' : 'Disabled'}</label>
                        <LemonSwitch
                            id={switchId}
                            checked={featureFlag.active}
                            onChange={(active) =>
                                featureFlag.id ? updateFeatureFlag({ id: featureFlag.id, payload: { active } }) : null
                            }
                            style={{ marginLeft: '0.5rem' }}
                        />
                    </div>
                )
            },
        },
        {
            width: 100,
            render: function Render(_, featureFlag: FeatureFlagType) {
                const [isPopupVisible, setIsPopupVisible] = useState(false)

                return (
                    <LemonButton
                        compact
                        icon={<IconEllipsis />}
                        type="stealth"
                        onClick={() => {
                            setIsPopupVisible((state) => !state)
                        }}
                        popup={{
                            visible: isPopupVisible,
                            onClickOutside: () => setIsPopupVisible(false),
                            placement: 'bottom-end',
                            actionable: true,
                            overlay: (
                                <>
                                    <LemonButton type="stealth" to={`/feature_flags/${featureFlag.id}`} fullWidth>
                                        Edit
                                    </LemonButton>
                                    <LemonButton
                                        type="stealth"
                                        to={`/insights?events=[{"id":"$pageview","name":"$pageview","type":"events","math":"dau"}]&breakdown_type=event&breakdown=$feature/${featureFlag.key}`}
                                        data-attr="usage"
                                        fullWidth
                                    >
                                        Use in Insights
                                    </LemonButton>
                                    <LemonSpacer />
                                    {featureFlag.id && (
                                        <LemonButton
                                            type="stealth"
                                            style={{ color: 'var(--danger)' }}
                                            to={`/feature_flags/${featureFlag.id}`}
                                            onClick={() => {
                                                deleteWithUndo({
                                                    endpoint: `projects/${currentTeamId}/feature_flags`,
                                                    object: { name: featureFlag.name, id: featureFlag.id },
                                                    callback: loadFeatureFlags,
                                                })
                                            }}
                                            fullWidth
                                        >
                                            Delete feature flag
                                        </LemonButton>
                                    )}
                                </>
                            ),
                        }}
                    />
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
            <div>
                <Input.Search
                    allowClear
                    enterButton
                    style={{ maxWidth: 400, width: 'initial', flexGrow: 1 }}
                    value={searchTerm}
                    onChange={(e) => {
                        setSearchTerm(e.target.value)
                    }}
                />
                <div className="mb float-right">
                    <LinkButton
                        type="primary"
                        to={urls.featureFlag('new')}
                        data-attr="new-feature-flag"
                        icon={<PlusOutlined />}
                    >
                        New Feature Flag
                    </LinkButton>
                </div>
            </div>
            <LemonTable
                dataSource={searchedFeatureFlags}
                columns={columns}
                onRow={(featureFlag) => ({
                    style: !featureFlag.active ? { color: 'var(--muted)' } : {},
                })}
                data-attr="feature-flag-table"
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
