import { useValues } from 'kea'
import { combineUrl } from 'kea-router'
import posthog from 'posthog-js'

import { IconInfo } from '@posthog/icons'
import { LemonMenu, LemonTable, LemonTableColumns, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import { ActivityTab } from '~/types'

import { SDK_DOCS_LINKS, SDK_TYPE_READABLE_NAME } from './sdkConstants'
import { AugmentedTeamSdkVersionsInfoRelease, type SdkType, sdkDoctorLogic } from './sdkDoctorLogic'

// NOTE: this SQL query, the activity page URL builder below, and the three tooltip
// messages further down are mirrored in products/growth/backend/sdk_health.py so the
// SDK Doctor MCP tool returns the same strings. Keep them in sync when editing here.
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
        title: (
            <span>
                VERSION{' '}
                <Tooltip
                    title={
                        <>
                            Click on a version number to view events captured.
                            <br />
                            Hover over status for version age and/or suggestion.
                        </>
                    }
                >
                    <IconInfo />
                </Tooltip>
            </span>
        ),
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

export function SdkSection({ sdkType }: { sdkType: SdkType }): JSX.Element {
    const { augmentedData, rawDataLoading: loading } = useValues(sdkDoctorLogic)

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
