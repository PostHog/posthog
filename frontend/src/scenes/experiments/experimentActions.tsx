import { LemonCheckbox, LemonDialog } from '@posthog/lemon-ui'

import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { Experiment } from '~/types'

import { hasEnded, isExperimentExposureFrozen } from './experimentsLogic'

/** Whether an experiment is in a state where it can be archived (ignoring permissions). */
export function canArchiveExperiment(
    experiment: Pick<Experiment, 'archived' | 'start_date' | 'end_date' | 'status'>
): boolean {
    return !experiment.archived && hasEnded(experiment)
}

/** Whether a running, unpaused experiment can have its exposure frozen (ignoring permissions). */
export function canFreezeExposure(
    experiment: Pick<Experiment, 'start_date' | 'end_date' | 'status' | 'feature_flag'>
): boolean {
    // Freezing exposure narrows the flag to a person cohort, which group-aggregated flags can't use.
    const isGroupAggregated = experiment.feature_flag?.filters?.aggregation_group_type_index != null
    return !isExperimentExposureFrozen(experiment) && !isGroupAggregated
}

export function confirmFreezeExposure(onConfirm: () => void): void {
    LemonDialog.open({
        title: 'Freeze exposure?',
        content: (
            <div className="text-sm text-secondary max-w-md">
                <p>
                    <b>New</b> users can no longer enroll. Everyone already enrolled keeps their variant, and metrics
                    keep updating — useful for measuring long-term impact (revenue, retention, renewals) after you stop
                    adding new users.
                </p>
                <p>
                    This snapshots the currently-exposed users into a static cohort and narrows the feature flag to it.
                    The experiment <b>keeps running</b> (it is not ended), so results keep flowing. End the experiment
                    when you're done measuring.
                </p>
            </div>
        ),
        primaryButton: {
            children: 'Freeze exposure',
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

export function confirmArchiveExperiment(
    experiment: Pick<Experiment, 'feature_flag'>,
    onConfirm: (disableFeatureFlag: boolean) => void
): void {
    // Only an enabled flag needs a decision — a disabled flag is archived automatically.
    const flagIsEnabled = !!experiment.feature_flag?.active
    let disableFeatureFlag = false

    LemonDialog.open({
        title: 'Archive this experiment?',
        content: (
            <div className="flex flex-col gap-3">
                <div className="text-sm text-secondary">
                    This action will hide the experiment from the list by default. It can be restored at any time.
                </div>
                {flagIsEnabled && (
                    <LemonCheckbox
                        defaultChecked={false}
                        onChange={(checked) => {
                            disableFeatureFlag = checked
                        }}
                        label={
                            <span>
                                Also disable and archive the linked feature flag{' '}
                                <code>{experiment.feature_flag?.key}</code>. It's still enabled — if your code still
                                references it, users will fall back to the default. Only do this after removing it from
                                your codebase.
                            </span>
                        }
                    />
                )}
            </div>
        ),
        primaryButton: {
            children: 'Archive',
            type: 'primary',
            onClick: () => onConfirm(disableFeatureFlag),
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
