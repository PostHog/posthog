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
                    <p className="text-muted">
                        Each job below shows the data it needs. Results will replace this page when clusters are ready.
                        You can leave this page while jobs run.
                    </p>
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
