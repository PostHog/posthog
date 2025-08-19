import { IconBolt, IconEllipsis, IconStethoscope, IconWarning } from '@posthog/icons'
import {
    LemonButton,
    LemonMenu,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTagProps,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconWithBadge } from 'lib/lemon-ui/icons'
import React from 'react'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { SdkType, SdkVersionInfo, sidePanelSdkDoctorLogic } from './sidePanelSdkDoctorLogic'

// Helper function to create enhanced event URLs with SDK debugging columns
const createEnhancedEventUrl = (eventId: string, timestamp: string): string => {
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
    const { sdkHealth, featureFlagMisconfiguration, outdatedSdkCount } = useValues(sidePanelSdkDoctorLogic)

    // TODO: Multi-init detection temporarily disabled for post-MVP
    // const { multipleInitSdks } = useValues(sidePanelSdkDoctorLogic)
    // const hasMultipleInits = multipleInitSdks.length > 0
    const hasMultipleInits = false
    const hasFlagMisconfiguration = featureFlagMisconfiguration.detected

    const title = hasFlagMisconfiguration
        ? 'Feature flag misconfiguration detected!'
        : hasMultipleInits
          ? 'SDK initialization issue detected!'
          : outdatedSdkCount > 0
            ? 'Outdated SDKs found'
            : 'SDK health is good'

    return (
        <Tooltip title={title} placement="left">
            <span {...props}>
                <IconWithBadge
                    content={hasFlagMisconfiguration || hasMultipleInits ? '!!' : sdkHealth !== 'healthy' ? '!' : '✓'}
                    status={
                        hasFlagMisconfiguration || hasMultipleInits
                            ? 'danger'
                            : sdkHealth === 'critical'
                              ? 'danger'
                              : sdkHealth === 'warning'
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
        releases: 'https://github.com/PostHog/posthog-js-lite/blob/main/posthog-node/CHANGELOG.md',
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
    // TODO: Multi-init detection temporarily disabled for post-MVP
    // const { multipleInitDetection } = useValues(sidePanelSdkDoctorLogic)
    const { loadRecentEvents } = useActions(sidePanelSdkDoctorLogic)

    // Group the versions by SDK type (each SDK type gets its own table)
    const groupedVersions = sdkVersions.reduce(
        (acc, sdk) => {
            const sdkType = sdk.type
            const sdkName = sdkTypeMapping[sdkType]?.name || 'Other'

            if (!acc[sdkName]) {
                acc[sdkName] = []
            }
            acc[sdkName].push(sdk)
            return acc
        },
        {} as Record<string, SdkVersionInfo[]>
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
                // Debug logging for version comparison
                console.info(`[SDK Doctor UI] Rendering version for ${record.type}:`, {
                    version: record.version,
                    latestVersion: record.latestVersion,
                    isOutdated: record.isOutdated,
                    exactMatch: record.version === record.latestVersion,
                    versionType: typeof record.version,
                    latestVersionType: typeof record.latestVersion,
                })

                return (
                    <div className="flex items-center gap-2 justify-end">
                        <code className="text-xs font-mono bg-muted-highlight rounded-sm px-1 py-0.5">
                            {record.version}
                        </code>
                        {record.isOutdated ? (
                            <Tooltip
                                placement="right"
                                title={
                                    record.latestVersion
                                        ? `Latest version: ${record.latestVersion}`
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
                        {/* TODO: Multi-init detection temporarily disabled for post-MVP */}
                        {/* {record.multipleInitializations && (
                            <Tooltip
                                placement="right"
                                title={`SDK initialized multiple times (${record.initCount} times).`}
                            >
                                <LemonTag type="danger" className="shrink-0">
                                    Multiple init
                                </LemonTag>
                            </Tooltip>
                        )} */}
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
                            onClick: () => loadRecentEvents(),
                            disabledReason: recentEventsLoading ? 'Scan in progress' : undefined,
                        },
                    ]}
                >
                    <LemonButton size="small" icon={<IconEllipsis />} />
                </LemonMenu>
            </SidePanelPaneHeader>
            <div className="p-3 overflow-y-auto flex-1">
                {/* TODO: Multi-init detection temporarily disabled for post-MVP */}
                {/* Show warning for multiple initializations if detected */}
                {/* {(sdkVersions.some((sdk) => sdk.multipleInitializations) || multipleInitDetection.detected) && (
                    <Section title="Multiple SDK initializations detected">
                        <div className="p-3 bg-danger/10 rounded border border-danger/20">
                            <div className="flex items-start">
                                <IconWarning className="text-danger text-xl mt-0.5 mr-2 flex-shrink-0" />
                                <div>
                                    <p className="font-semibold">
                                        Whoops!
                                        <br />
                                        It looks like you're initializing the Web SDK multiple times
                                    </p>
                                    <p className="text-sm mt-1">
                                        This could be the same version being initialized where it already has been,
                                        and/or initializing different versions of `posthog-js` from different places in
                                        your code (or via third-party tools like Google Tag Manager, Shopify, etc.)
                                    </p>
                                    <p className="text-sm mt-1">
                                        This can cause problems; some obvious, some harder to notice. So, you'll want to
                                        remove the duplicate inits, and initialize `posthog-js` just once (preferably{' '}
                                        <Link
                                            to="https://github.com/PostHog/posthog-js/blob/main/packages/browser/CHANGELOG.md"
                                            target="_blank"
                                            targetBlankIcon
                                        >
                                            the latest version
                                        </Link>
                                        )
                                    </p>
                                    <div className="mt-2 flex gap-3">
                                        <Link
                                            to="https://posthog.com/docs/libraries/js/config"
                                            target="_blank"
                                            targetBlankIcon
                                        >
                                            View initialization docs
                                        </Link>
                                        {multipleInitDetection.detected && multipleInitDetection.exampleEventId && (
                                            <Link
                                                to={`/project/1/events/${
                                                    multipleInitDetection.exampleEventId
                                                }/${encodeURIComponent(
                                                    multipleInitDetection.exampleEventTimestamp || ''
                                                )}`}
                                                target="_blank"
                                                targetBlankIcon
                                            >
                                                View example event
                                            </Link>
                                        )}
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Table showing the URLs/screens where multiple initializations happen 
                        <div className="mt-3">
                            <h4 className="text-sm font-semibold mb-2">Source(s) of multiple initialization</h4>
                            <LemonTable
                                dataSource={
                                    // Use persistent detection data if available, otherwise fall back to current events
                                    multipleInitDetection.detected && multipleInitDetection.affectedUrls.length > 0
                                        ? multipleInitDetection.affectedUrls.map((url) => ({ url }))
                                        : sdkVersions
                                              .find((sdk) => sdk.multipleInitializations)
                                              ?.initUrls?.map((item) => ({
                                                  url: item.url,
                                              })) || [
                                              // Fallback data just in case
                                              {
                                                  url: 'Unknown source file',
                                              },
                                          ]
                                }
                                columns={[
                                    {
                                        title: 'URL / Screen',
                                        dataIndex: 'url',
                                        render: function RenderUrl(url) {
                                            return <code className="text-xs truncate max-w-48">{url}</code>
                                        },
                                    },
                                ]}
                                size="small"
                                className="ph-no-capture"
                            />
                        </div>
                    </Section>
                )} */}

                {/* Show warning for feature flag misconfigurations if detected */}
                {featureFlagMisconfiguration.detected && (
                    <Section title="Feature flag misconfiguration detected">
                        <div className="p-3 bg-danger/10 rounded border border-danger/20">
                            <div className="flex items-start">
                                <IconWarning className="text-danger text-xl mt-0.5 mr-2 flex-shrink-0" />
                                <div>
                                    <p className="font-semibold">Feature flag(s) called before PostHog loaded</p>
                                    <p className="text-sm mt-1">
                                        Ooops. It looks you're calling feature flags before PostHog has finished
                                        loading. This can cause flags to return incorrect values, make experiment
                                        results inaccurate, and cause inconsistent user experiences.
                                    </p>
                                    <p className="text-sm mt-1">
                                        To fix this: Use bootstrapping to make flags available instantly, or use{' '}
                                        <code>onFeatureFlags</code> to wait on PostHog before calling flags. (See the
                                        links below for details)
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
                                                            to="https://app.posthog.com/settings/project#snippet"
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
                        // TODO: Multi-init detection temporarily disabled for post-MVP
                        // !sdkVersions.some((sdk) => sdk.multipleInitializations) &&
                        // !multipleInitDetection.detected &&
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

                {/* Render a section for each SDK category with SDKs */}
                {Object.entries(groupedVersions).map(([category, categorySDKs]) => {
                    if (categorySDKs.length === 0) {
                        return null
                    }

                    // Check if any SDKs in this category are outdated
                    const outdatedSDKs = categorySDKs.filter((sdk) => sdk.isOutdated)

                    return (
                        <div key={category} className="mb-6">
                            <LemonTable
                                dataSource={categorySDKs.sort((a, b) => b.count - a.count)}
                                loading={recentEventsLoading}
                                columns={createColumns()}
                                className="ph-no-capture"
                                size="small"
                                emptyState="No SDK information found. Try scanning recent events."
                            />

                            {/* Show documentation links for all SDKs in this category */}
                            {categorySDKs.length > 0 && (
                                <div className="mt-2">
                                    <SdkLinks sdkType={categorySDKs[0].type} />
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
