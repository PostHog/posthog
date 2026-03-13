import { LemonDialog } from '@posthog/lemon-ui'

import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { Experiment } from '~/types'

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
    projectId: number
    experiment: Pick<Experiment, 'id' | 'name'>
    onDelete: () => void
}): void {
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
                    endpoint: `projects/${opts.projectId}/experiments`,
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
