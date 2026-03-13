import { LemonDialog } from '@posthog/lemon-ui'

import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { Experiment } from '~/types'

import { hasEnded } from './experimentsLogic'

/** Whether an experiment is in a state where it can be archived (ignoring permissions). */
export function canArchiveExperiment(
    experiment: Pick<Experiment, 'archived' | 'start_date' | 'end_date' | 'status'>
): boolean {
    return !experiment.archived && hasEnded(experiment)
}

export function confirmArchiveExperiment(onConfirm: () => void): void {
    LemonDialog.open({
        title: 'Archive this experiment?',
        content: (
            <div className="text-sm text-secondary">
                This action will hide the experiment from the list by default. It can be restored at any time.
            </div>
        ),
        primaryButton: {
            children: 'Archive',
            type: 'primary',
            onClick: onConfirm,
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}

export function confirmDeleteExperiment(opts: {
    projectId: number | null
    experiment: Pick<Experiment, 'id' | 'name'>
    onDelete: () => void
}): void {
    if (!opts.projectId) {
        return
    }
    const projectId = opts.projectId
    LemonDialog.open({
        title: 'Delete this experiment?',
        content: (
            <div className="text-sm text-secondary">
                Experiment with its settings will be deleted, but event data will be preserved.
            </div>
        ),
        primaryButton: {
            children: 'Delete',
            type: 'primary',
            onClick: () => {
                void deleteWithUndo({
                    endpoint: `projects/${projectId}/experiments`,
                    object: { name: opts.experiment.name, id: opts.experiment.id },
                    callback: opts.onDelete,
                })
            },
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}
