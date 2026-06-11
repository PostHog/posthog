import { IconPullRequest } from '@posthog/icons'

import { SignalReport } from '../../types'
import { PullRequestCard } from '../cards/PullRequestCard'

export function PullRequestsTab({ reports }: { reports: SignalReport[] }): JSX.Element {
    if (reports.length === 0) {
        return (
            <div className="mx-auto max-w-md flex flex-col items-center text-center py-16 px-6 gap-2">
                <div className="flex items-center justify-center h-12 w-12 rounded-full bg-fill-primary text-secondary mb-1">
                    <IconPullRequest className="text-2xl" />
                </div>
                <h3 className="text-base font-semibold m-0">No pull requests right now</h3>
                <p className="text-sm text-tertiary m-0">
                    When an agent ships a change, the PR draft lands here for you to review and publish.
                </p>
            </div>
        )
    }

    return (
        <div className="mx-auto max-w-4xl flex flex-col gap-3 px-6 py-4">
            {reports.map((report) => (
                <PullRequestCard key={report.id} report={report} />
            ))}
        </div>
    )
}
