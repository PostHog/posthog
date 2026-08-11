import { useValues } from 'kea'
import posthog from 'posthog-js'

import { IconInfo } from '@posthog/icons'
import { LemonMenu, LemonTable, LemonTableColumns, LemonTag, LemonTagType, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import { SDK_DOCS_LINKS, SDK_TYPE_READABLE_NAME } from './sdkConstants'
import { AugmentedTeamSdkVersionsInfoRelease, type SdkType, sdkHealthLogic } from './sdkHealthLogic'

/**
 * A version status tag that reveals its status reason on click and on keyboard focus, not just on
 * hover – users kept clicking the tag that flagged the problem they came here for and getting nothing.
 */
export function SdkVersionStatusTag({
    type,
    statusReason,
    children,
}: {
    type: LemonTagType
    statusReason: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <Tooltip placement="right" title={statusReason} openOnClick>
            <LemonTag type={type} className="shrink-0 cursor-help" tabIndex={0}>
                {children}
            </LemonTag>
        </Tooltip>
    )
}

// The version drill-in SQL and Activity page URL are computed by the backend (sql_query /
// activity_page_url on each release) so the UI and the SDK Health MCP tool stay in lockstep.
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
                            Hover or click a status for version age and/or suggestion.
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
                                disabledReason: record.activityPageUrl ? undefined : 'Unavailable for this version',
                                onClick: () => {
                                    posthog.capture('sdk doctor view events', {
                                        sdkType: record.type,
                                        destination: 'activity_page',
                                    })
                                    newInternalTab(record.activityPageUrl)
                                },
                            },
                            {
                                label: 'SQL query',
                                disabledReason: record.sqlQuery ? undefined : 'Unavailable for this version',
                                onClick: () => {
                                    posthog.capture('sdk doctor view events', {
                                        sdkType: record.type,
                                        destination: 'sql_editor',
                                    })
                                    newInternalTab(urls.sqlEditor({ query: record.sqlQuery }))
                                },
                            },
                        ]}
                    >
                        <code className="text-xs font-mono bg-muted-highlight rounded-sm cursor-pointer hover:bg-muted">
                            {record.version}
                        </code>
                    </LemonMenu>
                    {record.isOutdated ? (
                        <SdkVersionStatusTag type="danger" statusReason={record.statusReason}>
                            {record.migrationRequired ? 'Migration required' : 'Outdated'}
                        </SdkVersionStatusTag>
                    ) : record.isCurrentOrNewer ? (
                        <SdkVersionStatusTag type="success" statusReason={record.statusReason}>
                            Current
                        </SdkVersionStatusTag>
                    ) : (
                        <SdkVersionStatusTag type="warning" statusReason={record.statusReason}>
                            Recent
                        </SdkVersionStatusTag>
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
    const { augmentedData, reportLoading: loading } = useValues(sdkHealthLogic)

    const sdk = augmentedData[sdkType]!
    const links = SDK_DOCS_LINKS[sdkType]
    const sdkName = SDK_TYPE_READABLE_NAME[sdkType]
    const migrationReason = sdk.migrationRequired ? sdk.allReleases[0]?.statusReason : undefined

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
                        {migrationReason && <small className="block text-muted-alt">{migrationReason}</small>}
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
