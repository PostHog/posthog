import { IconStethoscope } from '@posthog/icons'
import { Tooltip, LemonTable, LemonBadge, LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconWithBadge } from 'lib/lemon-ui/icons'
import React from 'react'

import { sidePanelSdkDoctorLogic, SdkVersionInfo } from './sidePanelSdkDoctorLogic'

export const SidePanelSdkDoctorIcon = (props: { className?: string }): JSX.Element => {
    const { sdkHealth } = useValues(sidePanelSdkDoctorLogic)
    
    const title =
        sdkHealth === 'warning'
            ? 'SDK issues detected'
            : sdkHealth === 'critical'
                ? 'Critical SDK issues detected'
                : 'SDK health is good'

    return (
        <Tooltip title={title} placement="left">
            <span {...props}>
                <IconWithBadge
                    content={sdkHealth !== 'healthy' ? '!' : '✓'}
                    status={sdkHealth === 'critical' ? 'danger' : sdkHealth === 'warning' ? 'warning' : 'success'}
                >
                    <IconStethoscope />
                </IconWithBadge>
            </span>
        </Tooltip>
    )
}

export function SidePanelSdkDoctor(): JSX.Element {
    const { sdkVersions, sdkHealth, recentEventsLoading, outdatedSdkCount } = useValues(sidePanelSdkDoctorLogic)
    const { loadRecentEvents } = useActions(sidePanelSdkDoctorLogic)

    return (
        <div className="p-4">
            <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-semibold mb-0">SDK Doctor</h3>
                <LemonButton
                    onClick={() => loadRecentEvents()}
                    type="primary"
                    size="small"
                    loading={recentEventsLoading}
                >
                    Scan events
                </LemonButton>
            </div>
            
            {sdkHealth !== 'healthy' ? (
                <div className="mb-4 p-3 bg-warning/10 rounded border border-warning/20">
                    <LemonBadge 
                        status={sdkHealth === 'critical' ? 'danger' : 'warning'}
                        className="mb-2"
                    >
                        {sdkHealth === 'critical' ? 'Critical' : 'Warning'}
                    </LemonBadge>
                    <p>
                        {outdatedSdkCount} {outdatedSdkCount === 1 ? 'SDK is' : 'SDKs are'} outdated and should be upgraded 
                        to ensure proper functionality and performance.
                    </p>
                    <p className="text-sm mt-2">
                        Using outdated SDKs may result in missing features, compatibility issues, 
                        or reduced performance. We recommend upgrading to the latest versions.
                    </p>
                </div>
            ) : (
                <div className="mb-4 p-3 bg-success/10 rounded border border-success/20">
                    <LemonBadge status="success" className="mb-2">Healthy</LemonBadge>
                    <p>All SDKs are up to date. No action needed.</p>
                </div>
            )}
            
            <h4 className="font-semibold mb-2">SDK Versions</h4>
            <LemonTable
                dataSource={sdkVersions}
                loading={recentEventsLoading}
                columns={[
                    {
                        title: 'SDK Type',
                        dataIndex: 'type',
                        render: function RenderType(type) {
                            return <div>{type}</div>
                        },
                    },
                    {
                        title: 'Version',
                        dataIndex: 'version',
                        render: function RenderVersion(version, record: SdkVersionInfo) {
                            return (
                                <div className="flex items-center gap-2">
                                    {version}
                                    {record.isOutdated && (
                                        <Tooltip 
                                            placement="right"
                                            title={record.latestVersion ? `Latest version: ${record.latestVersion}` : 'Upgrade recommended'}
                                        >
                                            <LemonBadge status="warning" className="text-xs">
                                                {record.releasesAhead && record.releasesAhead > 0 ? 
                                                    `${record.releasesAhead} versions behind` : 'Outdated'}
                                            </LemonBadge>
                                        </Tooltip>
                                    )}
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Events',
                        dataIndex: 'count',
                        render: function RenderCount(count) {
                            return <div className="text-right">{count}</div>
                        },
                    },
                ]}
                emptyState="No SDK information found. Try scanning recent events."
            />
        </div>
    )
}
