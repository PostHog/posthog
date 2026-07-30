import { Link } from '@posthog/lemon-ui'

import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import type { HealthIssue } from '../types'
import { dismissActionColumn, severityColumn } from './healthTableColumns'

const SOURCE_MAPS_DOCS_URL = 'https://posthog.com/docs/error-tracking/upload-source-maps'

function missingSourceMapsDescription(issue: HealthIssue): string {
    const { unresolved_pct, unresolved_frames, total_frames, lookback_hours } = issue.payload
    const percent = Math.round((Number(unresolved_pct) || 0) * 100)
    const frames =
        unresolved_frames != null && total_frames != null
            ? ` (${Number(unresolved_frames).toLocaleString()} of ${Number(total_frames).toLocaleString()})`
            : ''
    return `${percent}% of JavaScript stack frames${frames} were unresolved in the last ${
        Number(lookback_hours) || 24
    } hours. Unresolved frames also degrade issue grouping. Upload source maps so stack traces show your original source code and errors group correctly.`
}

export function ErrorTrackingHealthTable({
    issues,
    onDismiss,
    onUndismiss,
}: {
    issues: HealthIssue[]
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
        dismissActionColumn(onDismiss, onUndismiss),
    ]

    return <LemonTable dataSource={issues} columns={columns} embedded size="small" rowClassName="group" />
}
