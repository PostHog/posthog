import { FeatureFlagType } from '~/types'

export interface LinkedExperiment {
    id: number
    name: string
}

export interface ExperimentLockReasons {
    variantKey?: string
    removeVariant?: string
    flagType?: string
}

/**
 * A running experiment reads its variant keys from the linked flag, so the API rejects a save that
 * drops or renames one. Draft, stopped and completed experiments do not block, and payloads,
 * descriptions and rollout percentages stay editable throughout.
 */
export function getRunningLinkedExperiment(
    featureFlag: Pick<FeatureFlagType, 'experiment_set_metadata'>
): LinkedExperiment | null {
    const experiment = featureFlag.experiment_set_metadata?.find((candidate) => candidate.is_running)
    return experiment ? { id: experiment.id, name: experiment.name } : null
}

export function getExperimentLockReasons(experiment: LinkedExperiment | null): ExperimentLockReasons {
    if (!experiment) {
        return {}
    }

    return {
        variantKey: `Variant keys are fixed while the experiment "${experiment.name}" runs.`,
        removeVariant: `Variants can't be removed while the experiment "${experiment.name}" runs.`,
        flagType: `The flag type can't change while the experiment "${experiment.name}" runs.`,
    }
}
