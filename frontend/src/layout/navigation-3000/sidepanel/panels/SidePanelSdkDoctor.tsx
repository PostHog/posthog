import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import posthog from 'posthog-js'

import { IconInfo, IconStethoscope } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonMenu,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { IconWithBadge } from 'lib/lemon-ui/icons'
import { inStorybook, inStorybookTestRunner } from 'lib/utils'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { ActivityTab } from '~/types'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import {
    AugmentedTeamSdkVersionsInfoRelease,
    type OutdatedTrafficAlert,
    type SdkType,
    sidePanelSdkDoctorLogic,
} from './sidePanelSdkDoctorLogic'

export const SDK_TYPE_READABLE_NAME: Record<SdkType, string> = {
    web: 'Web',
    'posthog-ios': 'iOS',
    'posthog-android': 'Android',
    'posthog-node': 'Node.js',
    'posthog-python': 'Python',
    'posthog-php': 'PHP',
    'posthog-ruby': 'Ruby',
    'posthog-go': 'Go',
    'posthog-flutter': 'Flutter',
    'posthog-react-native': 'React Native',
    'posthog-dotnet': '.NET',
    'posthog-elixir': 'Elixir',
}

// SDK documentation links mapping
const SDK_DOCS_LINKS: Record<SdkType, { releases: string; docs: string }> = {
    web: {
        releases: 'https://github.com/PostHog/posthog-js/blob/main/packages/browser/CHANGELOG.md',
        docs: 'https://posthog.com/docs/libraries/js',
    },
    'posthog-ios': {
        releases: 'https://github.com/PostHog/posthog-ios/releases',
        docs: 'https://posthog.com/docs/libraries/ios',
    },
    'posthog-android': {
        releases: 'https://github.com/PostHog/posthog-android/releases',
        docs: 'https://posthog.com/docs/libraries/android',
    },
    'posthog-node': {
        releases: 'https://github.com/PostHog/posthog-js/blob/main/packages/node/CHANGELOG.md',
        docs: 'https://posthog.com/docs/libraries/node',
    },
    'posthog-python': {
        releases: 'https://github.com/PostHog/posthog-python/releases',
        docs: 'https://posthog.com/docs/libraries/python',
    },
    'posthog-php': {
        releases: 'https://github.com/PostHog/posthog-php/releases',
        docs: 'https://posthog.com/docs/libraries/php',
    },
    'posthog-ruby': {
        releases: 'https://github.com/PostHog/posthog-ruby/releases',
        docs: 'https://posthog.com/docs/libraries/ruby',
    },
    'posthog-go': {
        releases: 'https://github.com/PostHog/posthog-go/releases',
        docs: 'https://posthog.com/docs/libraries/go',
    },
    'posthog-flutter': {
        releases: 'https://github.com/PostHog/posthog-flutter/releases',
        docs: 'https://posthog.com/docs/libraries/flutter',
    },
    'posthog-react-native': {
        releases: 'https://github.com/PostHog/posthog-js/blob/main/packages/react-native/CHANGELOG.md',
        docs: 'https://posthog.com/docs/libraries/react-native',
    },
    'posthog-dotnet': {
        releases: 'https://github.com/PostHog/posthog-dotnet/releases',
        docs: 'https://posthog.com/docs/libraries/dotnet',
    },
    'posthog-elixir': {
        releases: 'https://github.com/PostHog/posthog-elixir/releases',
        docs: 'https://posthog.com/docs/libraries/elixir',
    },
}

const queryForSdkVersion = (sdkType: SdkType, version: string): string => {
    return `SELECT * FROM events WHERE timestamp >= NOW() - INTERVAL 7 DAY AND properties.$lib = '${sdkType}' AND properties.$lib_version = '${version}' ORDER BY timestamp DESC LIMIT 50`
}

// Matches the Activity explore page's DataTableNode format
const activityPageUrlForSdkVersion = (sdkType: SdkType, version: string): string => {
    const query = {
        kind: 'DataTableNode',
        columns: [
            '*',
            'event',
            'person_display_name -- Person',
            'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
            'properties.$lib',
            'timestamp',
        ],
        hiddenColumns: [],
        pinnedColumns: [],
        source: {
            kind: 'EventsQuery',
            select: [
                '*',
                'timestamp',
                'properties.$lib',
                'properties.$lib_version',
                'event',
                'person_display_name -- Person',
                'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
            ],
            orderBy: ['timestamp DESC'],
            after: '-7d',
            properties: [
                {
                    key: '$lib',
                    value: [sdkType],
                    operator: 'exact',
                    type: 'event',
                },
                {
                    key: '$lib_version',
                    value: [version],
                    operator: 'exact',
                    type: 'event',
                },
            ],
        },
        context: { type: 'team_columns' },
        allowSorting: true,
        embedded: false,
        expandable: true,
        full: true,
        propertiesViaUrl: true,
        showActions: true,
        showColumnConfigurator: true,
        showCount: false,
        showDateRange: true,
        showElapsedTime: false,
        showEventFilter: true,
        showEventsFilter: false,
        showExport: true,
        showHogQLEditor: true,
        showOpenEditorButton: true,
        showPersistentColumnConfigurator: true,
        showPropertyFilter: true,
        showRecordingColumn: false,
        showReload: true,
        showResultsTable: true,
        showSavedFilters: false,
        showSavedQueries: true,
        showSearch: true,
        showSourceQueryOptions: true,
        showTableViews: false,
        showTestAccountFilters: true,
        showTimings: false,
    }
    return combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: query }).url
}

const COLUMNS: LemonTableColumns<AugmentedTeamSdkVersionsInfoRelease> = [
    {
        title: 'Version',
        dataIndex: 'version',
        render: function RenderVersion(_, record) {
            return (
                <div className="flex items-center gap-2 justify-start">
                    <LemonMenu
                        items={[
                            {
                                label: 'Events on Activity page',
                                onClick: () => {
                                    posthog.capture('sdk doctor view events', {
                                        sdkType: record.type,
                                        destination: 'activity_page',
                                    })
                                    newInternalTab(activityPageUrlForSdkVersion(record.type, record.version))
                                },
                            },
                            {
                                label: 'SQL query',
                                onClick: () => {
                                    posthog.capture('sdk doctor view events', {
                                        sdkType: record.type,
                                        destination: 'sql_editor',
                                    })
                                    newInternalTab(
                                        urls.sqlEditor({
                                            query: queryForSdkVersion(record.type, record.version),
                                        })
                                    )
                                },
                            },
                        ]}
                    >
                        <code className="text-xs font-mono bg-muted-highlight rounded-sm cursor-pointer hover:bg-muted">
                            {record.version}
                        </code>
                    </LemonMenu>
                    {record.isOutdated ? (
                        <Tooltip
                            placement="right"
                            title={
                                record.releasedAgo
                                    ? `Released ${record.releasedAgo}. Upgrade recommended.`
                                    : 'Upgrade recommended'
                            }
                        >
                            <LemonTag type="danger" className="shrink-0 cursor-help">
                                Outdated
                            </LemonTag>
                        </Tooltip>
                    ) : record.isCurrentOrNewer ? (
                        <Tooltip
                            placement="right"
                            title={
                                <>
                                    You have the latest available.
                                    <br />
                                    Click 'Releases ↗' above to check for any since.
                                </>
                            }
                        >
                            <LemonTag type="success" className="shrink-0 cursor-help">
                                Current
                            </LemonTag>
                        </Tooltip>
                    ) : (
                        <Tooltip
                            placement="right"
                            title={
                                record.releasedAgo ? (
                                    <>
                                        Released {record.releasedAgo}.
                                        <br />
                                        Upgrading is a good idea, but it's not urgent yet.
                                    </>
                                ) : (
                                    "Upgrading is a good idea, but it's not urgent yet"
                                )
                            }
                        >
                            <LemonTag type="warning" className="shrink-0 cursor-help">
                                Recent
                            </LemonTag>
                        </Tooltip>
                    )}
                </div>
            )
        },
    },
    {
        title: (
            <span>
                LAST EVENT{' '}
                <Tooltip title="This gets refreshed every night, click 'Scan Events' to refresh manually">
                    <IconInfo />
                </Tooltip>
            </span>
        ),
        dataIndex: 'maxTimestamp',
        render: function RenderMaxTimestamp(_, record) {
            return <TZLabel time={record.maxTimestamp} />
        },
    },
    {
        title: '# events, last 7 days',
        dataIndex: 'count',
        render: function RenderCount(_, record) {
            return <div className="text-xs text-muted-alt">{record.count}</div>
        },
    },
]

export function SidePanelSdkDoctor(): JSX.Element | null {
    const {
        augmentedData,
        rawDataLoading: loading,
        needsUpdatingCount,
        hasErrors,
        snoozedUntil,
    } = useValues(sidePanelSdkDoctorLogic)
    const { isDev } = useValues(preflightLogic)

    const { loadRawData, snoozeSdkDoctor } = useActions(sidePanelSdkDoctorLogic)

    useOnMountEffect(() => {
        posthog.capture('sdk doctor loaded', { needsUpdatingCount })
    })

    const scanEvents = (): void => {
        posthog.capture('sdk doctor scan events')
        loadRawData({ forceRefresh: true })
    }

    const snoozeWarning = (): void => {
        posthog.capture('sdk doctor snooze warning')
        snoozeSdkDoctor()
    }

    return (
        <div className="flex flex-col h-full">
            <SidePanelPaneHeader
                title={
                    <span>
                        SDK Doctor{' '}
                        <LemonTag type="warning" className="ml-1">
                            Beta
                        </LemonTag>
                    </span>
                }
            >
                <LemonButton
                    size="xsmall"
                    type="primary"
                    disabledReason={loading ? 'Scan in progress' : undefined}
                    onClick={scanEvents}
                >
                    {loading ? 'Scanning events...' : 'Scan events'}
                </LemonButton>
            </SidePanelPaneHeader>

            {/* Explain to devs how they can get the SDK data to show up */}
            {isDev && !inStorybook() && !inStorybookTestRunner() && (
                <div className="m-2 mb-4">
                    <LemonBanner type="info">
                        <strong>DEVELOPMENT WARNING!</strong> When running in development, make sure you've run the
                        appropriate Dagster jobs: <LemonTag>cache_all_team_sdk_versions_job</LemonTag> and{' '}
                        <LemonTag>cache_github_sdk_versions_job</LemonTag>. Data won't be available otherwise.
                    </LemonBanner>
                </div>
            )}

            {/* Beta feedback banner */}
            <div className="m-2">
                <LemonBanner type="info">
                    <strong>SDK Doctor is in Beta!</strong> Help us improve by sharing your feedback?{' '}
                    <Link to="#panel=support%3Asupport%3Asdk%3Alow%3Atrue">Send feedback</Link>
                </LemonBanner>
            </div>

            <div className="p-3">
                {loading ? null : hasErrors ? (
                    <div className="text-center text-muted p-4">
                        Error loading SDK information. Please try again later.
                    </div>
                ) : Object.keys(augmentedData).length === 0 ? (
                    <div className="text-center text-muted p-4">
                        No SDK information found. Are you sure you have our SDK installed? You can scan events to get
                        started.
                    </div>
                ) : needsUpdatingCount === 0 ? (
                    <section className="mb-2">
                        <h3>SDK health is good</h3>
                        <LemonBanner type="success" hideIcon={false}>
                            <p className="font-semibold">All caught up! Your SDKs are up to date.</p>
                            <p className="text-sm mt-1">You've got the latest. Nice work keeping everything current.</p>
                        </LemonBanner>
                    </section>
                ) : (
                    <section className="mb-2">
                        <h3>Time for an update!</h3>
                        <LemonBanner
                            type="warning"
                            hideIcon={false}
                            action={{
                                children: 'Snooze warning for 30 days',
                                disabledReason: snoozedUntil ? 'Already snoozed' : undefined,
                                onClick: snoozeWarning,
                            }}
                        >
                            {Object.entries(augmentedData).flatMap(([sdkType, sdk]) =>
                                sdk.outdatedTrafficAlerts.map((alert: OutdatedTrafficAlert) => (
                                    <p key={`${sdkType}-${alert.version}`} className="text-sm mb-1">
                                        Version <code className="text-xs font-mono">{alert.version}</code> of the{' '}
                                        {SDK_TYPE_READABLE_NAME[sdkType as SdkType]} SDK has captured more than{' '}
                                        {alert.thresholdPercent}% of events in the last 7 days.
                                    </p>
                                ))
                            )}
                            <p className="font-semibold">
                                An outdated SDK means you're missing out on bug fixes and enhancements.
                            </p>
                            <p className="text-sm mt-1">
                                <Link to="https://posthog.com/docs/sdk-doctor/keeping-sdks-current" target="_blank">
                                    Learn how
                                </Link>{' '}
                                to keep your SDK versions current.
                            </p>
                            <p className="text-sm mt-1">See the 'Releases' and 'Docs' links below for more info.</p>
                        </LemonBanner>
                    </section>
                )}
            </div>

            {Object.keys(augmentedData).map((sdkType) => (
                <SdkSection key={sdkType} sdkType={sdkType as SdkType} />
            ))}
        </div>
    )
}

export const SidePanelSdkDoctorIcon = (props: { className?: string }): JSX.Element => {
    const { needsAttention, needsUpdatingCount, sdkHealth } = useValues(sidePanelSdkDoctorLogic)

    const title = needsAttention
        ? 'Needs attention'
        : needsUpdatingCount > 0
          ? 'Outdated SDKs found'
          : 'SDK health is good'

    return (
        <Tooltip title={title} placement="left">
            <span {...props}>
                <IconWithBadge content={needsUpdatingCount > 0 ? '!' : '✓'} status={sdkHealth}>
                    <IconStethoscope />
                </IconWithBadge>
            </span>
        </Tooltip>
    )
}

export function SdkSection({ sdkType }: { sdkType: SdkType }): JSX.Element {
    const { augmentedData, rawDataLoading: loading } = useValues(sidePanelSdkDoctorLogic)

    const sdk = augmentedData[sdkType]!
    const links = SDK_DOCS_LINKS[sdkType]
    const sdkName = SDK_TYPE_READABLE_NAME[sdkType]

    return (
        <div className="flex flex-col mb-4 p-2">
            <div className="flex flex-row justify-between items-center gap-2 mb-4">
                <div>
                    <h3 className="mb-0">{sdkName}</h3>
                    <Tooltip
                        title={
                            <>
                                Version number cached once a day.
                                <br />
                                Click 'Releases ↗' to check for any since.
                            </>
                        }
                    >
                        <small className="cursor-help">Latest version available: {sdk.currentVersion}</small>
                    </Tooltip>
                </div>

                <div className="flex flex-row gap-2">
                    <Link to={links.releases} target="_blank" targetBlankIcon>
                        Releases
                    </Link>
                    <Link to={links.docs} target="_blank" targetBlankIcon>
                        Docs
                    </Link>
                    <Link
                        to="https://posthog.com/docs/sdk-doctor/keeping-sdks-current#ways-to-keep-sdk-versions-current"
                        target="_blank"
                        targetBlankIcon
                    >
                        Updating
                    </Link>
                </div>
            </div>

            <LemonTable
                dataSource={sdk.allReleases}
                loading={loading}
                columns={COLUMNS}
                size="small"
                emptyState="No SDK information found. Try scanning recent events."
            />
        </div>
    )
}
