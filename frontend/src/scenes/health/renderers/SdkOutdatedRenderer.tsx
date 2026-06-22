import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
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

const statusTag = (entry: UsageEntry): JSX.Element => {
    const tag = entry.is_latest ? (
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

export const SdkOutdatedRenderer = ({ issue }: { issue: HealthIssue }): JSX.Element => {
    const sdkName = issue.payload.sdk_name as SdkType | undefined
    const latestVersion = issue.payload.latest_version as string | undefined
    const reason = issue.payload.reason as string | undefined
    const usage = issue.payload.usage as UsageEntry[] | undefined

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
                <table className="w-full text-xs border-collapse">
                    <thead>
                        <tr className="text-muted">
                            <th className="text-left font-medium py-1 pr-2">Version</th>
                            <th className="text-right font-medium py-1 pr-2">Events (7d)</th>
                            <th className="text-left font-medium py-1 pr-2">Last seen</th>
                            <th className="text-left font-medium py-1">Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {usage.map((entry) => (
                            <tr key={entry.lib_version} className="border-t border-border-light">
                                <td className="py-1 pr-2">
                                    <code className="text-xs">{entry.lib_version}</code>
                                </td>
                                <td className="text-right py-1 pr-2">{(entry.count ?? 0).toLocaleString()}</td>
                                <td className="py-1 pr-2">
                                    <TZLabel time={entry.max_timestamp} />
                                </td>
                                <td className="py-1">{statusTag(entry)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </div>
    )
}
