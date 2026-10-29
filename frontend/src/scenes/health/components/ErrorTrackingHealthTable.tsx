import { Link } from '@posthog/lemon-ui'

import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import type { HealthIssue } from '../types'
import { issueActionsColumn, severityColumn } from './healthTableColumns'

const SOURCE_MAPS_DOCS_URL = 'https://posthog.com/docs/error-tracking/upload-source-maps'

const SOURCE_MAPS_PLATFORM_LABELS: Record<string, { platform: string; symbols: string }> = {
    javascript: { platform: 'JavaScript', symbols: 'source maps' },
    java: { platform: 'Android', symbols: 'mapping files' },
    native: { platform: 'iOS and native', symbols: 'debug symbols' },
}

function missingSourceMapsDescription(issue: HealthIssue): string {
    const { unresolved_pct, unresolved_frames, total_frames, lookback_hours, platform } = issue.payload
    const percent = Math.round((Number(unresolved_pct) || 0) * 100)
    const frames =
        unresolved_frames != null && total_frames != null
            ? ` (${Number(unresolved_frames).toLocaleString()} of ${Number(total_frames).toLocaleString()})`
            : ''
    // Payloads written before per-platform scoring have no platform, and they counted JavaScript frames only.
    const labels =
        SOURCE_MAPS_PLATFORM_LABELS[String(platform ?? 'javascript')] ?? SOURCE_MAPS_PLATFORM_LABELS.javascript
    return `${percent}% of ${labels.platform} stack frames that need ${labels.symbols}${frames} were missing them in the last ${
        Number(lookback_hours) || 24
    } hours. Unresolved frames also degrade issue grouping. Upload ${labels.symbols} so stack traces show your original source code and errors group correctly.`
}

export function ErrorTrackingHealthTable({
    issues,
    onSnooze,
    onDismiss,
    onUndismiss,
}: {
    issues: HealthIssue[]
    onSnooze: (id: string, duration: string) => void
    onDismiss: (id: string) => void
    onUndismiss: (id: string) => void
}): JSX.Element {
    const columns: LemonTableColumns<HealthIssue> = [
        {
            title: 'Check',
            key: 'check',
            render: function Render(_, issue: HealthIssue) {
                return (
                    <div className="py-1">
                        <div className="flex items-center gap-2">
                            <span className="font-medium">Source maps</span>
                            <Link to={SOURCE_MAPS_DOCS_URL} className="text-xs text-muted">
                                Docs
                            </Link>
                        </div>
                        <div className="text-xs text-muted mt-0.5">{missingSourceMapsDescription(issue)}</div>
                    </div>
                )
            },
        },
        severityColumn(),
        issueActionsColumn(onSnooze, onDismiss, onUndismiss),
    ]

    return <LemonTable dataSource={issues} columns={columns} embedded size="small" rowClassName="group" />
}
