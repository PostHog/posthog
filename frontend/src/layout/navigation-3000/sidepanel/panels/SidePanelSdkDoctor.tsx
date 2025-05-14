import { IconStethoscope, IconEllipsis } from '@posthog/icons'
import { Tooltip, LemonTable, LemonBadge, LemonButton, LemonMenu, LemonTag, LemonTableColumns, LemonTagProps } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconWithBadge } from 'lib/lemon-ui/icons'
import React from 'react'

import { sidePanelSdkDoctorLogic, SdkVersionInfo, SdkType } from './sidePanelSdkDoctorLogic'
import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'

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

// SDK type to human-readable name and color mapping
const sdkTypeMapping: Record<SdkType, { name: string; color: LemonTagProps['type'] }> = {
    web: { name: 'Web', color: 'primary' },
    ios: { name: 'iOS', color: 'highlight' },
    android: { name: 'Android', color: 'success' },
    node: { name: 'Node.js', color: 'warning' },
    python: { name: 'Python', color: 'primary' },
    php: { name: 'PHP', color: 'default' },
    ruby: { name: 'Ruby', color: 'danger' },
    go: { name: 'Go', color: 'muted' },
    flutter: { name: 'Flutter', color: 'default' },
    'react-native': { name: 'React Native', color: 'highlight' },
    other: { name: 'Other', color: 'default' }
}

// SDK category grouping
const sdkCategories: Record<string, SdkType[]> = {
    'Web': ['web'],
    'Mobile': ['ios', 'android', 'flutter', 'react-native'],
    'Backend': ['node', 'python', 'php', 'ruby', 'go'],
    'Other': ['other']
}

export function SidePanelSdkDoctor(): JSX.Element {
    const { sdkVersions, sdkHealth, recentEventsLoading, outdatedSdkCount } = useValues(sidePanelSdkDoctorLogic)
    const { loadRecentEvents } = useActions(sidePanelSdkDoctorLogic)

    // Group the versions by SDK category
    const groupedVersions = sdkVersions.reduce((acc, sdk) => {
        // Find which category this SDK belongs to
        let category = 'Other'
        for (const [cat, types] of Object.entries(sdkCategories)) {
            if (types.includes(sdk.type)) {
                category = cat
                break
            }
        }
        
        if (!acc[category]) {
            acc[category] = []
        }
        acc[category].push(sdk)
        return acc
    }, {} as Record<string, SdkVersionInfo[]>)

    // Create a flattened array with category headings
    const tableData: (SdkVersionInfo & { isCategoryHeader?: boolean; category?: string })[] = []
    
    Object.entries(groupedVersions).forEach(([category, sdks]) => {
        if (sdks.length > 0) {
            // Add category header
            tableData.push({ 
                type: 'other',
                version: '',
                isOutdated: false,
                count: 0,
                isCategoryHeader: true,
                category
            })
            
            // Add SDK versions in this category, sorted by count
            tableData.push(...sdks.sort((a, b) => b.count - a.count))
        }
    })

    const columns: LemonTableColumns<typeof tableData[0]> = [
        {
            title: 'SDK',
            dataIndex: 'type',
            render: function RenderType(_, record) {
                if (record.isCategoryHeader) {
                    return <div className="font-semibold text-sm text-muted-0 p-1">{record.category}</div>
                }
                
                const sdkInfo = sdkTypeMapping[record.type] || { name: record.type, color: 'default' }
                return (
                    <div className="flex items-center">
                        <LemonTag type={sdkInfo.color} className="uppercase">
                            {sdkInfo.name}
                        </LemonTag>
                    </div>
                )
            },
        },
        {
            title: 'Version',
            dataIndex: 'version',
            render: function RenderVersion(_, record) {
                if (record.isCategoryHeader) {
                    return null
                }
                
                return (
                    <div className="flex items-center gap-2">
                        <code className="text-xs font-mono bg-muted-highlight rounded-sm px-1 py-0.5">
                            {record.version}
                        </code>
                        {record.isOutdated && (
                            <Tooltip 
                                placement="right"
                                title={record.latestVersion ? `Latest version: ${record.latestVersion}` : 'Upgrade recommended'}
                            >
                                <LemonTag type="warning" className="shrink-0">
                                    Outdated
                                </LemonTag>
                            </Tooltip>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Events',
            dataIndex: 'count',
            render: function RenderCount(_, record) {
                if (record.isCategoryHeader) {
                    return null
                }
                
                return <div className="text-right font-medium">{record.count}</div>
            },
        },
    ]

    return (
        <div className="flex flex-col h-full overflow-hidden">
            <SidePanelPaneHeader title="SDK Doctor">
                <LemonMenu
                    items={[
                        {
                            label: recentEventsLoading ? 'Scanning events...' : 'Scan events',
                            onClick: () => loadRecentEvents(),
                            disabledReason: recentEventsLoading ? 'Scan in progress' : undefined,
                        },
                    ]}
                >
                    <LemonButton size="small" icon={<IconEllipsis />} />
                </LemonMenu>
            </SidePanelPaneHeader>
            <div className="p-4 overflow-y-auto flex-1">
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
                        <ul className="list-disc pl-5 mt-3 text-sm">
                            <li>
                                <a 
                                    href="https://github.com/PostHog/posthog-js/releases" 
                                    target="_blank" 
                                    rel="noopener noreferrer"
                                    className="text-primary hover:text-primary-dark"
                                >
                                    Releases page on GitHub
                                </a>
                            </li>
                            <li>
                                <a 
                                    href="https://posthog.com/docs/libraries/js" 
                                    target="_blank" 
                                    rel="noopener noreferrer"
                                    className="text-primary hover:text-primary-dark"
                                >
                                    Web SDK docs
                                </a>
                            </li>
                            {outdatedSdkCount > 0 && sdkVersions.some(sdk => sdk.type === 'php' && sdk.isOutdated) && (
                                <>
                                    <li>
                                        <a 
                                            href="https://github.com/PostHog/posthog-php/blob/master/History.md" 
                                            target="_blank" 
                                            rel="noopener noreferrer"
                                            className="text-primary hover:text-primary-dark"
                                        >
                                            PHP SDK Releases
                                        </a>
                                    </li>
                                    <li>
                                        <a 
                                            href="https://posthog.com/docs/libraries/php" 
                                            target="_blank" 
                                            rel="noopener noreferrer"
                                            className="text-primary hover:text-primary-dark"
                                        >
                                            PHP SDK docs
                                        </a>
                                    </li>
                                </>
                            )}
                        </ul>
                    </div>
                ) : (
                    <div className="mb-4 p-3 bg-success/10 rounded border border-success/20">
                        <LemonBadge status="success" className="mb-2">Healthy</LemonBadge>
                        <p>All SDKs are up to date. No action needed.</p>
                        <ul className="list-disc pl-5 mt-3 text-sm">
                            <li>
                                <a 
                                    href="https://github.com/PostHog/posthog-js/releases" 
                                    target="_blank" 
                                    rel="noopener noreferrer"
                                    className="text-primary hover:text-primary-dark"
                                >
                                    Releases page on GitHub
                                </a>
                            </li>
                            <li>
                                <a 
                                    href="https://posthog.com/docs/libraries/js" 
                                    target="_blank" 
                                    rel="noopener noreferrer"
                                    className="text-primary hover:text-primary-dark"
                                >
                                    Web SDK docs
                                </a>
                            </li>
                        </ul>
                    </div>
                )}
                
                <h4 className="font-semibold mb-2">SDK Versions</h4>
                <LemonTable
                    dataSource={tableData}
                    loading={recentEventsLoading}
                    columns={columns}
                    className="ph-no-capture"
                    size="small"
                    rowClassName={(record) => record.isCategoryHeader ? 'bg-side category-row' : ''}
                    emptyState="No SDK information found. Try scanning recent events."
                />
            </div>
        </div>
    )
}
