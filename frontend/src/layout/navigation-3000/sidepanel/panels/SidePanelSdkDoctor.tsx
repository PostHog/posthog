import { useActions, useValues } from 'kea'

import { IconInfo, IconStethoscope } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTableColumns, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconWithBadge } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { inStorybook, inStorybookTestRunner } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { AugmentedTeamSdkVersionsInfoRelease, type SdkType, sidePanelSdkDoctorLogic } from './sidePanelSdkDoctorLogic'

const SDK_TYPE_READABLE_NAME: Record<SdkType, string> = {
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
        releases: 'https://github.com/PostHog/posthog-php/blob/master/History.md',
        docs: 'https://posthog.com/docs/libraries/php',
    },
    'posthog-ruby': {
        releases: 'https://github.com/PostHog/posthog-ruby/blob/main/CHANGELOG.md',
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
        releases: 'https://github.com/PostHog/posthog-elixir/blob/master/CHANGELOG.md',
        docs: 'https://posthog.com/docs/libraries/elixir',
    },
}

const COLUMNS: LemonTableColumns<AugmentedTeamSdkVersionsInfoRelease> = [
    {
        title: 'Version',
        dataIndex: 'version',
        render: function RenderVersion(_, record) {
            return (
                <div className="flex items-center gap-2 justify-end">
                    <code className="text-xs font-mono bg-muted-highlight rounded-sm px-1 py-0.5">
                        {record.version}
                    </code>
                    {record.isOutdated ? (
                        <Tooltip
                            placement="right"
                            title={`Upgrade recommended ${record.daysSinceRelease ? `(${Math.floor(record.daysSinceRelease / 7)} weeks old)` : ''}`}
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
                        <LemonTag type="success" className="shrink-0">
                            Recent
                        </LemonTag>
                    )}
                </div>
            )
        },
    },
    {
        title: (
            <span>
                LAST EVENT AT{' '}
                <Tooltip title="This gets refreshed every 6 hours, click 'Scan Events' to refresh manually">
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
        title: '# Events in the last 7 days',
        dataIndex: 'count',
        render: function RenderCount(_, record) {
            return <div className="text-xs text-muted-alt">{record.count}</div>
        },
    },
]

export function SidePanelSdkDoctor(): JSX.Element | null {
    const { sdkVersionsMap, sdkVersionsLoading, teamSdkVersionsLoading, outdatedSdkCount, hasErrors, snoozedUntil } =
        useValues(sidePanelSdkDoctorLogic)
    const { isDev } = useValues(preflightLogic)

    const { loadTeamSdkVersions, snoozeSdkDoctor } = useActions(sidePanelSdkDoctorLogic)

    const loading = sdkVersionsLoading || teamSdkVersionsLoading

    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.SDK_DOCTOR_BETA]) {
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
                />
                <div className="m-2">
                    <LemonBanner type="info">
                        <div>
                            <strong>SDK Doctor is in beta!</strong> It's not enabled in your account yet.
                        </div>
                    </LemonBanner>
                </div>
            </div>
        )
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
                    onClick={() => loadTeamSdkVersions({ forceRefresh: true })}
                >
                    {loading ? 'Scanning events...' : 'Scan events'}
                </LemonButton>
            </SidePanelPaneHeader>

            {/* Explain to devs how they can get the SDK data to show up */}
            {isDev && !inStorybook() && !inStorybookTestRunner() && (
                <div className="m-2 mb-4">
                    <LemonBanner type="info">
                        <strong>DEVELOPMENT WARNING!</strong> When running in development, make sure you've run the
                        appropriate Dasgter jobs: <LemonTag>cache_all_team_sdk_versions_job</LemonTag> and{' '}
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
                ) : Object.keys(sdkVersionsMap).length === 0 ? (
                    <div className="text-center text-muted p-4">
                        No SDK information found. Are you sure you have our SDK installed? You can scan events to get
                        started.
                    </div>
                ) : outdatedSdkCount === 0 ? (
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
                                onClick: () => snoozeSdkDoctor(),
                            }}
                        >
                            <p className="font-semibold">
                                An outdated SDK means you're missing out on bug fixes and enhacements.
                            </p>
                            <p className="text-sm mt-1">Check the links below to get caught up.</p>
                        </LemonBanner>
                    </section>
                )}
            </div>

            {Object.keys(sdkVersionsMap).map((sdkType) => (
                <SdkSection key={sdkType} sdkType={sdkType as SdkType} />
            ))}
        </div>
    )
}

export const SidePanelSdkDoctorIcon = (props: { className?: string }): JSX.Element => {
    const { sdkHealth, outdatedSdkCount } = useValues(sidePanelSdkDoctorLogic)

    const title = outdatedSdkCount > 0 ? 'Outdated SDKs found' : 'SDK health is good'

    return (
        <Tooltip title={title} placement="left">
            <span {...props}>
                <IconWithBadge content={outdatedSdkCount > 0 ? '!' : '✓'} status={sdkHealth}>
                    <IconStethoscope />
                </IconWithBadge>
            </span>
        </Tooltip>
    )
}

function SdkSection({ sdkType }: { sdkType: SdkType }): JSX.Element {
    const { sdkVersionsMap, teamSdkVersionsLoading } = useValues(sidePanelSdkDoctorLogic)

    const sdk = sdkVersionsMap[sdkType]!
    const links = SDK_DOCS_LINKS[sdkType]
    const sdkName = SDK_TYPE_READABLE_NAME[sdkType]

    return (
        <div className="flex flex-col mb-4 p-2">
            <div className="flex flex-row justify-between items-center gap-2 mb-4">
                <div>
                    <div className="flex flex-row gap-2">
                        <h3 className="mb-0">{sdkName}</h3>
                        <span>
                            <LemonTag type={sdk.isOutdated ? 'warning' : 'success'}>
                                {sdk.isOutdated ? 'Outdated' : 'Up to date'}
                            </LemonTag>
                        </span>

                        {sdk.isOld && (
                            <LemonTag type="warning" className="shrink-0">
                                Old
                            </LemonTag>
                        )}
                    </div>
                    <small>Current version: {sdk.currentVersion}</small>
                </div>

                <div className="flex flex-row gap-2">
                    <Link to={links.releases} target="_blank" targetBlankIcon>
                        Releases
                    </Link>
                    <Link to={links.docs} target="_blank" targetBlankIcon>
                        Docs
                    </Link>
                </div>
            </div>

            <LemonTable
                dataSource={sdk.allReleases}
                loading={teamSdkVersionsLoading}
                columns={COLUMNS}
                size="small"
                emptyState="No SDK information found. Try scanning recent events."
            />
        </div>
    )
}
