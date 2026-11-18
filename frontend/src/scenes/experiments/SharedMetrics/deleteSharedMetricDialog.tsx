import { LemonDialog, Link, lemonToast } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { experimentSavedMetricsRetrieve } from 'products/experiments/frontend/generated/api'
import type { ExperimentSavedMetricLinkedExperimentApi } from 'products/experiments/frontend/generated/api.schemas'

/**
 * Deleting a shared metric cascades: it disappears from every experiment using it. Linkage is
 * always fetched fresh here, because list responses carry it empty and a detail page's copy can
 * predate an experiment launched after the page loaded. A failed fetch blocks the dialog: an
 * unwarned delete is worse than a retry.
 */
/** The running experiments that use the metric, or null when that couldn't be checked. */
export async function fetchRunningExperimentsForSharedMetric(
    projectId: number | string,
    sharedMetricId: number
): Promise<readonly ExperimentSavedMetricLinkedExperimentApi[] | null> {
    try {
        const response = await experimentSavedMetricsRetrieve(String(projectId), sharedMetricId)
        return (response.linked_experiments || []).filter((experiment) => experiment.is_running)
    } catch {
        lemonToast.error('Could not check which experiments use this metric. Try again.')
        return null
    }
}

export const DELETE_SHARED_METRIC_TITLE = 'Delete this metric?'

export function DeleteSharedMetricCopy({
    runningExperiments,
}: {
    runningExperiments: readonly ExperimentSavedMetricLinkedExperimentApi[]
}): JSX.Element {
    return runningExperiments.length > 0 ? (
        <div className="flex max-w-120 flex-col gap-2">
            <p className="m-0">
                This metric is used by{' '}
                {runningExperiments.length === 1
                    ? 'a running experiment'
                    : `${runningExperiments.length} running experiments`}
                . Deleting it also removes it from{' '}
                {runningExperiments.length === 1 ? 'that experiment and its' : 'those experiments and their'} results.
            </p>
            <ul className="m-0 max-h-60 list-disc space-y-1 overflow-y-auto pl-4">
                {runningExperiments.map((experiment) => (
                    <li key={experiment.id} className="truncate">
                        <Link to={urls.experiment(experiment.id)}>{experiment.name}</Link>
                    </li>
                ))}
            </ul>
            <p className="m-0">This action cannot be undone.</p>
        </div>
    ) : (
        <div>This action cannot be undone.</div>
    )
}

export async function openDeleteSharedMetricDialog({
    projectId,
    sharedMetricId,
    onDelete,
}: {
    projectId: number | string
    sharedMetricId: number
    onDelete: () => void
}): Promise<void> {
    const runningExperiments = await fetchRunningExperimentsForSharedMetric(projectId, sharedMetricId)
    if (runningExperiments === null) {
        return
    }

    LemonDialog.open({
        title: DELETE_SHARED_METRIC_TITLE,
        content: (
            <div className="text-sm text-secondary">
                <DeleteSharedMetricCopy runningExperiments={runningExperiments} />
            </div>
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
