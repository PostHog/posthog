import { ClusteringEnabledSwitch } from '../clusters/ClusteringEnabledSwitch'
import { ClusteringJobsButton } from '../clusters/ClusteringJobsButton'
import { ClusteringProgress } from '../clusters/ClusteringProgress'

export function ClustersWaitingState(): JSX.Element {
    return (
        <div className="space-y-4">
            <div className="flex items-center justify-end gap-2 flex-wrap">
                <ClusteringEnabledSwitch />
                <ClusteringJobsButton />
            </div>
            <div className="mx-auto max-w-3xl space-y-4 py-8">
                <div>
                    <h2>Clustering is enabled</h2>
                    <p className="text-muted">Your clusters will appear here when they’re ready.</p>
                </div>
                <ClusteringProgress />
                <p className="text-sm text-muted">
                    A job can finish without finding clusters. For example, ten traces about unrelated topics may not
                    form any groups.
                </p>
            </div>
        </div>
    )
}
