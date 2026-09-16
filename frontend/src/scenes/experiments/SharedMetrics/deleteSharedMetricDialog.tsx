import { LemonDialog, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { experimentSavedMetricsRetrieve } from 'products/experiments/frontend/generated/api'
import type { ExperimentSavedMetricLinkedExperimentApi } from 'products/experiments/frontend/generated/api.schemas'

/**
 * Deleting a shared metric cascades: it disappears from every experiment using it. The list
 * endpoint returns `linked_experiments` empty, so callers without the loaded metric leave
 * `linkedExperiments` undefined and the dialog fetches them before opening.
 */
export async function openDeleteSharedMetricDialog({
    projectId,
    sharedMetricId,
    linkedExperiments,
    onDelete,
}: {
    projectId: number | string
    sharedMetricId: number
    linkedExperiments?: readonly ExperimentSavedMetricLinkedExperimentApi[]
    onDelete: () => void
}): Promise<void> {
    let experiments = linkedExperiments
    if (experiments === undefined) {
        try {
            const response = await experimentSavedMetricsRetrieve(String(projectId), sharedMetricId)
            experiments = response.linked_experiments
        } catch {
            experiments = []
        }
    }
    const runningExperiments = (experiments || []).filter((experiment) => experiment.is_running)

    LemonDialog.open({
        title: 'Delete this metric?',
        content:
            runningExperiments.length > 0 ? (
                <div className="text-sm text-secondary max-w-120">
                    <p>
                        This metric is used by{' '}
                        {runningExperiments.length === 1
                            ? 'a running experiment'
                            : `${runningExperiments.length} running experiments`}
                        . Deleting it also removes it from{' '}
                        {runningExperiments.length === 1 ? 'that experiment and its' : 'those experiments and their'}{' '}
                        results.
                    </p>
                    <ul className="list-disc pl-4 space-y-1 max-h-60 overflow-y-auto">
                        {runningExperiments.map((experiment) => (
                            <li key={experiment.id} className="truncate">
                                <Link to={urls.experiment(experiment.id)}>{experiment.name}</Link>
                            </li>
                        ))}
                    </ul>
                    <p>This action cannot be undone.</p>
                </div>
            ) : (
                <div className="text-sm text-secondary">This action cannot be undone.</div>
            ),
        primaryButton: {
            children: 'Delete',
            type: 'primary',
            onClick: onDelete,
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}
