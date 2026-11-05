import { LemonTable, LemonTableColumns, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { SDK_DOCS_LINKS, SDK_TYPE_READABLE_NAME } from 'scenes/onboarding/shared/sdkHealth/sdkConstants'
import type { SdkType } from 'scenes/onboarding/shared/sdkHealth/sdkHealthLogic'

import type { HealthIssue } from '../types'

interface UsageEntry {
    lib_version: string
    count: number
    max_timestamp: string
    release_date: string | null
    is_latest: boolean
    is_outdated?: boolean
    status_reason?: string
}

const statusTag = (entry: UsageEntry, migrationRequired: boolean): JSX.Element => {
    const tag = migrationRequired ? (
        <LemonTag type="danger" size="small">
            Migration required
        </LemonTag>
    ) : entry.is_latest ? (
        <LemonTag type="success" size="small">
            Current
        </LemonTag>
    ) : entry.is_outdated ? (
        <LemonTag type="danger" size="small">
            Outdated
        </LemonTag>
    ) : (
        <LemonTag type="warning" size="small">
            Behind
        </LemonTag>
    )
    return entry.status_reason ? <Tooltip title={entry.status_reason}>{tag}</Tooltip> : tag
}

const usageColumns = (migrationRequired: boolean): LemonTableColumns<UsageEntry> => [
    {
        title: 'Version',
        key: 'lib_version',
        render: (_, entry) => <code className="text-xs">{entry.lib_version}</code>,
    },
    {
        title: 'Events (7d)',
        key: 'count',
        align: 'right',
        render: (_, entry) => (entry.count ?? 0).toLocaleString(),
        sorter: (a, b) => (a.count ?? 0) - (b.count ?? 0),
    },
    {
        title: 'Last seen',
        key: 'max_timestamp',
        render: (_, entry) => <TZLabel time={entry.max_timestamp} />,
        sorter: (a, b) => dayjs(a.max_timestamp).valueOf() - dayjs(b.max_timestamp).valueOf(),
    },
    {
        title: 'Status',
        key: 'status',
        render: (_, entry) => statusTag(entry, migrationRequired),
    },
]

export const SdkOutdatedRenderer = ({ issue }: { issue: HealthIssue }): JSX.Element => {
    const sdkName = issue.payload.sdk_name as SdkType | undefined
    const latestVersion = issue.payload.latest_version as string | undefined
    const reason = issue.payload.reason as string | undefined
    const usage = issue.payload.usage as UsageEntry[] | undefined
    const migrationRequired = typeof issue.payload.migration_target === 'string'

    if (!sdkName) {
        return <></>
    }

    const readableName = SDK_TYPE_READABLE_NAME[sdkName] ?? sdkName
    const links = SDK_DOCS_LINKS[sdkName]

    return (
        <div className="mt-2 text-xs">
            <div className="flex items-center justify-between mb-1">
                <span className="font-medium">
                    {readableName} SDK — latest: <code className="text-xs">{latestVersion}</code>
                </span>
                {links && (
                    <div className="flex gap-2">
                        <Link to={links.releases} target="_blank" targetBlankIcon className="text-xs">
                            Releases
                        </Link>
                        <Link to={links.docs} target="_blank" targetBlankIcon className="text-xs">
                            Docs
                        </Link>
                    </div>
                )}
            </div>
            {reason && <div className="text-muted mb-2">{reason}</div>}
            {usage && usage.length > 0 && (
                <LemonTable
                    dataSource={usage}
                    columns={usageColumns(migrationRequired)}
                    rowKey="lib_version"
                    // The Health page renders several of these tables, and URL sorting shares one
                    // `order` param across all of them.
                    useURLForSorting={false}
                    embedded
                    size="small"
                />
            )}
        </div>
    )
}
