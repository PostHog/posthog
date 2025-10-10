import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React, { useEffect, useRef } from 'react'

import { IconBolt, IconEllipsis, IconStethoscope, IconWarning } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonMenu,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTagProps,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { IconWithBadge } from 'lib/lemon-ui/icons'
import { getAppContext } from 'lib/utils/getAppContext'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import type { SdkType, SdkVersionInfo } from './sdk_doctor/types'
import { sidePanelSdkDoctorLogic } from './sidePanelSdkDoctorLogic'

const IS_DEBUG_MODE = (() => {
    const appContext = getAppContext()
    return appContext?.preflight?.is_debug || process.env.NODE_ENV === 'test'
})()

// Helper function to create enhanced event URLs with SDK debugging columns
const createEnhancedEventUrl = (eventId: string, timestamp: string): string => {
    try {
        const eventTime = new Date(timestamp).getTime()
        const timeWindow = 30000 // 30 seconds window around the event
        const before = new Date(eventTime + timeWindow).toISOString()
        const after = new Date(eventTime - timeWindow).toISOString()

        const query = {
            kind: 'DataTableNode',
            full: true,
            source: {
                kind: 'EventsQuery',
                select: [
                    '*',
                    'person_display_name -- Person',
                    'event',
                    'properties.$session_id',
                    'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
                    'properties.$feature_flag',
                    'properties.$lib',
                    'properties.$lib_version',
                    'timestamp',
                ],
                orderBy: ['timestamp DESC'],
                after,
                properties: [
                    {
                        type: 'hogql',
                        key: `uuid = '${eventId}'`,
                        value: null,
                    },
                ],
                modifiers: {
                    usePresortedEventsTable: true,
                },
                before,
            },
            propertiesViaUrl: true,
            showSavedQueries: true,
            showPersistentColumnConfigurator: true,
        }

        const encodedQuery = encodeURIComponent(JSON.stringify(query))
        return `/project/1/activity/explore#q=${encodedQuery}`
    } catch (error) {
        posthog.captureException(error)
        // Fallback to simple event URL
        return `/project/1/events/${eventId}/${encodeURIComponent(timestamp)}`
    }
}

const Section = ({ title, children }: { title: string; children: React.ReactNode }): React.ReactElement => {
    return (
        <section className="mb-6">
            <>
                <h3>{title}</h3>
                {children}
            </>
        </section>
    )
}

export const SidePanelSdkDoctorIcon = (props: { className?: string }): JSX.Element => {
    const { menuIconStatus, featureFlagMisconfiguration, outdatedSdkCount } = useValues(sidePanelSdkDoctorLogic)

    const hasFlagMisconfiguration = featureFlagMisconfiguration.detected

    const title = hasFlagMisconfiguration
        ? 'Feature flag misconfiguration detected!'
        : outdatedSdkCount > 0
          ? 'Outdated SDKs found'
          : menuIconStatus === 'warning'
            ? 'Some SDKs have newer versions available'
            : 'SDK health is good'

    return (
        <Tooltip title={title} placement="left">
            <span {...props}>
                <IconWithBadge
                    content={
                        hasFlagMisconfiguration
                            ? '!!'
                            : menuIconStatus !== 'healthy' && outdatedSdkCount > 0
                              ? '!'
                              : '✓'
                    }
                    status={
                        hasFlagMisconfiguration
                            ? 'danger'
                            : menuIconStatus === 'critical'
                              ? 'danger'
                              : outdatedSdkCount > 0
                                ? 'danger' // Red circle for any outdated SDKs
                                : menuIconStatus === 'warning'
                                  ? 'warning'
                                  : 'success'
                    }
                >
                    <IconStethoscope />
                </IconWithBadge>
            </span>
        </Tooltip>
    )
}

// SDK type to human-readable name and color mapping
const sdkTypeMapping: Record<SdkType, { name: string; color: LemonTagProps['type'] }> = {
    web: { name: 'Web', color: 'warning' },
    ios: { name: 'iOS', color: 'warning' },
    android: { name: 'Android', color: 'warning' },
    node: { name: 'Node.js', color: 'warning' },
    python: { name: 'Python', color: 'warning' },
    php: { name: 'PHP', color: 'warning' },
    ruby: { name: 'Ruby', color: 'warning' },
    go: { name: 'Go', color: 'warning' },
    flutter: { name: 'Flutter', color: 'warning' },
    'react-native': { name: 'React Native', color: 'warning' },
    dotnet: { name: '.NET', color: 'warning' },
    elixir: { name: 'Elixir', color: 'warning' },
    other: { name: 'Other', color: 'default' },
}

// SDK documentation links mapping
const sdkDocsLinks: Record<SdkType, { releases: string; docs: string }> = {
    web: {
        releases: 'https://github.com/PostHog/posthog-js/blob/main/packages/browser/CHANGELOG.md',
        docs: 'https://posthog.com/docs/libraries/js',
    },
    ios: {
        releases: 'https://github.com/PostHog/posthog-ios/releases',
        docs: 'https://posthog.com/docs/libraries/ios',
    },
    android: {
        releases: 'https://github.com/PostHog/posthog-android/releases',
        docs: 'https://posthog.com/docs/libraries/android',
    },
    node: {
        releases: 'https://github.com/PostHog/posthog-js/blob/main/packages/node/CHANGELOG.md',
        docs: 'https://posthog.com/docs/libraries/node',
    },
    python: {
        releases: 'https://github.com/PostHog/posthog-python/releases',
        docs: 'https://posthog.com/docs/libraries/python',
    },
    php: {
        releases: 'https://github.com/PostHog/posthog-php/blob/master/History.md',
        docs: 'https://posthog.com/docs/libraries/php',
    },
    ruby: {
        releases: 'https://github.com/PostHog/posthog-ruby/blob/main/CHANGELOG.md',
        docs: 'https://posthog.com/docs/libraries/ruby',
    },
    go: {
        releases: 'https://github.com/PostHog/posthog-go/releases',
        docs: 'https://posthog.com/docs/libraries/go',
    },
    flutter: {
        releases: 'https://github.com/PostHog/posthog-flutter/releases',
        docs: 'https://posthog.com/docs/libraries/flutter',
    },
    'react-native': {
        releases: 'https://github.com/PostHog/posthog-js/blob/main/packages/react-native/CHANGELOG.md',
        docs: 'https://posthog.com/docs/libraries/react-native',
    },
    dotnet: {
        releases: 'https://github.com/PostHog/posthog-dotnet/releases',
        docs: 'https://posthog.com/docs/libraries/dotnet',
    },
    elixir: {
        releases: 'https://github.com/PostHog/posthog-elixir/blob/master/CHANGELOG.md',
        docs: 'https://posthog.com/docs/libraries/elixir',
    },
    other: {
        releases: 'https://github.com/PostHog',
        docs: 'https://posthog.com/docs/libraries',
    },
}

// Component to render SDK links
const SdkLinks = ({ sdkType }: { sdkType: SdkType }): JSX.Element => {
    const links = sdkDocsLinks[sdkType]
    const sdkName = sdkTypeMapping[sdkType].name

    return (
        <div className="flex justify-between items-center py-2 text-sm border-t border-border mt-2">
            <Link to={links.releases} target="_blank" targetBlankIcon>
                {sdkName} SDK {sdkType === 'web' ? 'Changelog' : 'Releases'}
            </Link>
            <Link to={links.docs} target="_blank" targetBlankIcon>
                {sdkName} SDK docs
            </Link>
        </div>
    )
}

export function SidePanelSdkDoctor(): JSX.Element {
    const { sdkVersions, recentEventsLoading, featureFlagMisconfiguration } = useValues(sidePanelSdkDoctorLogic)
    const { loadRecentEvents, loadTeamSdkDetections } = useActions(sidePanelSdkDoctorLogic)

    // Debug log once on mount (debug mode only)
    const hasLoggedRef = useRef(false)
    useEffect(() => {
        if (!hasLoggedRef.current && IS_DEBUG_MODE) {
            console.info('[SDK Doctor UI] Component mounted with versions:', sdkVersions)
            hasLoggedRef.current = true
        }
    }, [sdkVersions])

    // NEW: Group by device context first, then by SDK type
    const groupedVersions = sdkVersions.reduce(
        (acc, sdk) => {
            // Group by device context first
            const deviceContext = sdk.deviceContext || 'mixed'
            const categoryName =
                deviceContext === 'mobile' ? 'Mobile Apps' : deviceContext === 'desktop' ? 'Web & Desktop' : 'Other'

            if (!acc[categoryName]) {
                acc[categoryName] = {}
            }

            // Then group by SDK name within each category
            const sdkType = sdk.type
            const sdkName = sdkTypeMapping[sdkType]?.name || 'Other'

            if (!acc[categoryName][sdkName]) {
                acc[categoryName][sdkName] = []
            }
            acc[categoryName][sdkName].push(sdk)
            return acc
        },
        {} as Record<string, Record<string, SdkVersionInfo[]>>
    )

    // Create table columns - used for all tables
    const createColumns = (): LemonTableColumns<SdkVersionInfo> => [
        {
            title: 'SDK',
            dataIndex: 'type',
            render: function RenderType(_, record) {
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
            align: 'right',
            render: function RenderVersion(_, record) {
                return (
                    <div className="flex items-center gap-2 justify-end">
                        <code className="text-xs font-mono bg-muted-highlight rounded-sm px-1 py-0.5">
                            {record.version}
                        </code>
                        {/* Error handling - show when SDK Doctor is unavailable */}
                        {record.error ? (
                            <Tooltip placement="right" title={record.error}>
                                <LemonTag type="muted" className="shrink-0">
                                    Unavailable
                                </LemonTag>
                            </Tooltip>
                        ) : record.isOutdated ? (
                            <Tooltip
                                placement="right"
                                title={
                                    record.latestVersion
                                        ? `Latest version: ${record.latestVersion}${
                                              record.daysSinceRelease
                                                  ? ` (${Math.floor(record.daysSinceRelease / 7)} weeks old)`
                                                  : ''
                                          }`
                                        : 'Upgrade recommended'
                                }
                            >
                                <LemonTag type="danger" className="shrink-0">
                                    Outdated
                                </LemonTag>
                            </Tooltip>
                        ) : record.latestVersion && record.version === record.latestVersion ? (
                            <LemonTag type="success" className="shrink-0">
                                Current
                            </LemonTag>
                        ) : (
                            <LemonTag type="primary" className="shrink-0">
                                Close enough
                            </LemonTag>
                        )}

                        {/* NEW: Volume indicator for context */}
                        {record.eventVolume === 'high' && (
                            <Tooltip title="High activity SDK">
                                <LemonTag type="highlight" className="shrink-0 text-xs">
                                    Active
                                </LemonTag>
                            </Tooltip>
                        )}
                    </div>
                )
            },
        },
    ]

    return (
        <div className="SidePanelSdkDoctor flex flex-col h-full overflow-hidden">
            <SidePanelPaneHeader title="SDK doctor">
                <LemonMenu
                    items={[
                        {
                            label: recentEventsLoading ? 'Scanning events...' : 'Scan events',
                            onClick: () => {
                                loadTeamSdkDetections(true)
                                loadRecentEvents()
                            },
                            disabledReason: recentEventsLoading ? 'Scan in progress' : undefined,
                        },
                    ]}
                >
                    <LemonButton size="small" icon={<IconEllipsis />} />
                </LemonMenu>
            </SidePanelPaneHeader>

            {/* Beta feedback banner */}
            <div className="p-3 border-b border-border">
                <LemonBanner type="info">
                    <div>
                        <strong>SDK Doctor is in... beta!</strong> Help us improve by sharing your feedback?{' '}
                        <Link to="#panel=support%3Asupport%3Asdk%3Alow%3Atrue">Send feedback</Link>
                    </div>
                </LemonBanner>
            </div>

            <div className="p-3 overflow-y-auto flex-1">
                {/* Show warning for feature flag misconfigurations if detected */}
                {featureFlagMisconfiguration.detected && (
                    <Section title="Possible feature flag misconfiguration">
                        <div className="p-3 bg-danger/10 rounded border border-danger/20">
                            <div className="flex items-start">
                                <IconWarning className="text-danger text-xl mt-0.5 mr-2 flex-shrink-0" />
                                <div>
                                    <p className="font-semibold">Feature flag(s) called before any other events</p>
                                    <p className="text-sm mt-1">
                                        Ooops. It looks like you're calling feature flags before any other events have
                                        been captured in the session. This can cause flags to return incorrect values,
                                        make experiment results inaccurate, and cause inconsistent user experiences.
                                    </p>
                                    <p className="text-sm mt-1">
                                        To fix this: Use bootstrapping to make flags available instantly, or use{' '}
                                        <code>onFeatureFlags</code> to wait on PostHog before calling flags.
                                        <br />
                                        (See the links below for details)
                                    </p>
                                    <div className="mt-2 flex gap-3">
                                        <Link
                                            to="https://posthog.com/docs/feature-flags/bootstrapping"
                                            target="_blank"
                                            disableDocsPanel
                                        >
                                            Bootstrapping docs
                                        </Link>
                                        <Link
                                            to="https://posthog.com/docs/libraries/js/features#ensuring-flags-are-loaded-before-usage"
                                            target="_blank"
                                            disableDocsPanel
                                        >
                                            'onFeatureFlags' docs
                                        </Link>
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Table showing the problematic flags */}
                        <div className="mt-3">
                            <h4 className="text-sm font-semibold mb-2">Flags called before loading</h4>
                            <LemonTable
                                dataSource={featureFlagMisconfiguration.flagsCalledBeforeLoading.map((flag) => ({
                                    flag,
                                    exampleEvent: featureFlagMisconfiguration.flagExampleEvents[flag],
                                }))}
                                columns={[
                                    {
                                        title: 'Feature Flag',
                                        dataIndex: 'flag',
                                        render: function RenderFlag(flag) {
                                            return <code className="text-xs">{flag}</code>
                                        },
                                    },
                                    {
                                        title: 'Example Event',
                                        dataIndex: 'exampleEvent',
                                        render: function RenderExampleEvent(exampleEvent) {
                                            if (!exampleEvent || typeof exampleEvent === 'string') {
                                                return <span className="text-muted text-xs">No example</span>
                                            }
                                            return (
                                                <Link
                                                    to={createEnhancedEventUrl(
                                                        exampleEvent.eventId,
                                                        exampleEvent.timestamp
                                                    )}
                                                    target="_blank"
                                                    targetBlankIcon
                                                    className="text-xs"
                                                >
                                                    View event
                                                </Link>
                                            )
                                        },
                                    },
                                ]}
                                size="small"
                                className="ph-no-capture"
                            />
                        </div>
                    </Section>
                )}

                {(() => {
                    // Count SDKs that need updating (both outdated and close enough)
                    const needsUpdateCount = sdkVersions.filter(
                        (sdk) => sdk.isOutdated || (sdk.latestVersion && sdk.version !== sdk.latestVersion)
                    ).length

                    return needsUpdateCount > 0 ? (
                        <Section title={needsUpdateCount === 1 ? 'Outdated SDK found' : 'Outdated SDKs found'}>
                            <div className="p-3 bg-warning/10 rounded border border-warning/20">
                                <div className="flex items-start">
                                    <IconWarning className="text-warning text-xl mt-0.5 mr-2 flex-shrink-0" />
                                    <div>
                                        <p className="font-semibold">
                                            <>{needsUpdateCount === 1 ? 'Your SDK has' : 'Your SDKs have'}</> fallen
                                            behind!
                                            <br />
                                            Time for an update...
                                        </p>
                                        <p className="text-sm mt-1">
                                            <>
                                                An outdated SDK means you're missing out on bug fixes and enhancements.
                                                {sdkVersions.some((sdk) => sdk.type === 'web' && sdk.isOutdated) && (
                                                    <>
                                                        {' '}
                                                        (If using our{' '}
                                                        <Link
                                                            to="/settings/project#snippet"
                                                            target="_blank"
                                                            targetBlankIcon
                                                            className="inline"
                                                        >
                                                            web snippet
                                                        </Link>{' '}
                                                        is an option for you, it will keep you up-to-date.)
                                                        <br />
                                                        <br />
                                                    </>
                                                )}
                                                {(() => {
                                                    // Check if we have multiple versions of the same SDK type
                                                    const sdkTypeCounts: Record<string, number> = {}
                                                    sdkVersions.forEach((sdk) => {
                                                        sdkTypeCounts[sdk.type] = (sdkTypeCounts[sdk.type] || 0) + 1
                                                    })
                                                    const hasMultipleVersions = Object.values(sdkTypeCounts).some(
                                                        (count) => count > 1
                                                    )
                                                    const hasWebSnippet = sdkVersions.some(
                                                        (sdk) => sdk.type === 'web' && sdk.isOutdated
                                                    )

                                                    return hasMultipleVersions ? (
                                                        <>
                                                            {!hasWebSnippet && ' '}
                                                            Multiple versions of the same SDK can cause inaccuracies in
                                                            your data.
                                                        </>
                                                    ) : null
                                                })()}
                                            </>
                                        </p>
                                        <p className="text-sm mt-1">Check the links below to get caught up.</p>
                                    </div>
                                </div>
                            </div>
                        </Section>
                    ) : (
                        !featureFlagMisconfiguration.detected && (
                            <Section title="SDK health is good">
                                <div className="p-3 bg-success/10 rounded border border-success/20">
                                    <div className="flex items-start">
                                        <IconBolt className="text-success text-xl mt-0.5 mr-2 flex-shrink-0" />
                                        <div>
                                            <p className="font-semibold">All caught up! Your SDKs are up to date.</p>
                                            <p className="text-sm mt-1">
                                                You've got the latest. Nice work keeping everything current.
                                            </p>
                                        </div>
                                    </div>
                                </div>
                            </Section>
                        )
                    )
                })()}

                {/* Render a section for each device context category */}
                {Object.entries(groupedVersions).map(([contextCategory, sdkGroups]) => {
                    // Flatten all SDKs in this context category
                    const allSDKsInCategory = Object.values(sdkGroups).flat()

                    if (allSDKsInCategory.length === 0) {
                        return null
                    }

                    return (
                        <div key={contextCategory} className="mb-6">
                            {/* Context category header */}
                            <h3 className="text-sm font-semibold text-muted-alt mb-2">{contextCategory}</h3>

                            <LemonTable
                                dataSource={allSDKsInCategory.sort((a, b) => b.count - a.count)}
                                loading={recentEventsLoading}
                                columns={createColumns()}
                                className="ph-no-capture"
                                size="small"
                                emptyState="No SDK information found. Try scanning recent events."
                            />

                            {/* Show documentation links for all SDKs in this category */}
                            {allSDKsInCategory.length > 0 && (
                                <div className="mt-2">
                                    {/* Get unique SDK types in this category */}
                                    {Array.from(new Set(allSDKsInCategory.map((sdk) => sdk.type))).map((sdkType) => (
                                        <SdkLinks key={sdkType} sdkType={sdkType} />
                                    ))}
                                </div>
                            )}
                        </div>
                    )
                })}

                {Object.keys(groupedVersions).length === 0 && (
                    <div className="text-center text-muted p-4">
                        No SDK information found. Try scanning recent events.
                    </div>
                )}
            </div>
        </div>
    )
}
