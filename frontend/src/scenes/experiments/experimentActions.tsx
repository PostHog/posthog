import { LemonCheckbox, LemonDialog } from '@posthog/lemon-ui'

import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { Experiment } from '~/types'

import { hasEnded, isExperimentExposureFrozen, isExperimentPaused, isLaunched } from './experimentsLogic'

/** Whether an experiment is in a state where it can be archived (ignoring permissions). */
export function canArchiveExperiment(
    experiment: Pick<Experiment, 'archived' | 'start_date' | 'end_date' | 'status'>
): boolean {
    return !experiment.archived && hasEnded(experiment)
}

/** Whether the experiment's flag release groups still carry the exposure-freeze stamps.
 * Unlike the status check, this also covers paused or stopped experiments whose flag was
 * frozen earlier — reset clears the stamps in all of those states. */
export function hasFrozenExposureStamps(experiment: Pick<Experiment, 'feature_flag'>): boolean {
    return !!experiment.feature_flag?.filters?.groups?.some((group) => group.exposure_frozen === true)
}

/** Whether an experiment can have its exposure frozen (ignoring permissions). */
export function canFreezeExposure(
    experiment: Pick<Experiment, 'start_date' | 'end_date' | 'status' | 'feature_flag' | 'holdout_id' | 'holdout'>
): boolean {
    const flagFilters = experiment.feature_flag?.filters
    // Freezing exposure narrows the flag to a person cohort, which group-aggregated flags can't use.
    const isGroupAggregated = flagFilters?.aggregation_group_type_index != null
    // Holdout assignment and early access enrollment (super_groups) are evaluated before release
    // conditions, so the freeze couldn't stop enrollment through them — the backend rejects these.
    const hasHoldout =
        experiment.holdout_id != null ||
        experiment.holdout != null ||
        !!flagFilters?.holdout ||
        !!flagFilters?.holdout_groups?.length
    const hasSuperGroups = !!flagFilters?.super_groups?.length
    return (
        isLaunched(experiment) &&
        !hasEnded(experiment) &&
        !isExperimentPaused(experiment) &&
        !isExperimentExposureFrozen(experiment) &&
        !isGroupAggregated &&
        !hasHoldout &&
        !hasSuperGroups
    )
}

export function confirmFreezeExposure(onConfirm: () => void): void {
    LemonDialog.open({
        title: 'Freeze exposure?',
        content: (
            <div className="text-sm text-secondary max-w-md">
                <p>
                    New users can <b>no longer enroll</b>. Everyone already enrolled keeps their variant, and metrics
                    keep updating — useful for measuring long-term impact (revenue, retention, renewals) after you stop
                    adding new users.
                </p>
                <p>
                    This snapshots the currently-exposed users into a static cohort and narrows the feature flag to it.
                    The experiment <b>keeps running</b>, so results keep updating.
                </p>
                <p>From a frozen state you can end an experiment or ship a variant at any time.</p>
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
