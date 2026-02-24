import { kindToLabel } from '../healthUtils'
import type { HealthIssue } from '../types'

export const GenericIssueRenderer = ({ issue }: { issue: HealthIssue }): JSX.Element => {
    if (Object.keys(issue.payload).length === 0) {
        return <></>
    }

    return (
        <div className="text-xs bg-surface-secondary rounded p-2 mt-1">
            {Object.entries(issue.payload).map(([key, value]) => (
                <div key={key} className="flex gap-2">
                    <span className="font-medium">{kindToLabel(key)}:</span>
                    <span className="break-all">
                        {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                    </span>
                </div>
            ))}
        </div>
    )
}
