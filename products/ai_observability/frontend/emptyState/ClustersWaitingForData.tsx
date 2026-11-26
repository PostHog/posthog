import { useActions } from 'kea'

import { IconBook, IconStack } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'

import { ClusteringEnabledSwitch } from '../clusters/ClusteringEnabledSwitch'
import { clusteringJobsLogic } from '../clusters/clusteringJobsLogic'
import { ClusteringJobsPanel } from '../clusters/ClusteringJobsPanel'

export function ClustersWaitingForData({ onDocs }: { onDocs: () => void }): JSX.Element {
    const { openJobsPanel } = useActions(clusteringJobsLogic)

    return (
        <>
            <LemonCard hoverEffect={false} className="w-full max-w-3xl mx-auto mt-6" data-attr="product-empty-state">
                <h2 className="mb-2">No clusters yet</h2>
                <p className="mb-6 text-secondary">
                    Jobs run automatically on a schedule. Clusters appear here when a job finds similar items that match
                    its filters.
                </p>

                <h3 className="text-base mb-3">Minimum data per job</h3>
                <dl className="space-y-3 mb-4">
                    <div>
                        <dt className="font-semibold">Traces</dt>
                        <dd className="text-secondary">10 traces from the last 7 days.</dd>
                    </div>
                    <div>
                        <dt className="font-semibold">Generations</dt>
                        <dd className="text-secondary">10 generations from different traces in the last 7 days.</dd>
                    </div>
                    <div>
                        <dt className="font-semibold">Evaluations</dt>
                        <dd className="text-secondary">
                            10 evaluation results from the last 3 days. Numeric and categorical scores are excluded.
                        </dd>
                    </div>
                </dl>
                <p className="text-secondary mb-6">
                    These minimums apply after filtering. Enough data alone doesn't guarantee a cluster. The items also
                    need to be similar enough in content to form a group.
                </p>

                <div className="flex items-center gap-3 flex-wrap">
                    <LemonButton
                        type="primary"
                        icon={<IconStack />}
                        onClick={openJobsPanel}
                        data-attr="clusters-jobs-button"
                    >
                        Manage jobs
                    </LemonButton>
                    <LemonButton
                        type="tertiary"
                        icon={<IconBook />}
                        to="https://posthog.com/docs/ai-observability/clusters"
                        targetBlank
                        onClick={onDocs}
                        data-attr="product-empty-state-docs"
                    >
                        Read the docs
                    </LemonButton>
                </div>

                <div className="mt-6 pt-4 border-t">
                    <ClusteringEnabledSwitch />
                </div>
            </LemonCard>
            <ClusteringJobsPanel />
        </>
    )
}
