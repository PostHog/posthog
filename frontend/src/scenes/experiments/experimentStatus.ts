// Leaf module: the toolbar imports these helpers, so they must not live in
// experimentsLogic (whose kea graph reaches the app's scene manifest).
import { Experiment, ExperimentStatus } from '~/types'

export type ExperimentStatusInput = Pick<Experiment, 'status' | 'start_date' | 'end_date'> | null | undefined

export function getExperimentStatus(experiment: ExperimentStatusInput): ExperimentStatus {
    if (!experiment) {
        return ExperimentStatus.Draft
    }

    if (experiment.status) {
        return experiment.status
    }

    // Fallback for stale fixtures and older mocked data without API-supplied status.
    if (experiment.end_date) {
        return ExperimentStatus.Stopped
    }
    if (experiment.start_date) {
        return ExperimentStatus.Running
    }
    return ExperimentStatus.Draft
}

export function isExperimentPaused(experiment: ExperimentStatusInput): boolean {
    return getExperimentStatus(experiment) === ExperimentStatus.Paused
}

export function isLaunched(experiment: ExperimentStatusInput): boolean {
    return getExperimentStatus(experiment) !== ExperimentStatus.Draft
}

export function hasEnded(experiment: ExperimentStatusInput): boolean {
    return getExperimentStatus(experiment) === ExperimentStatus.Stopped
}
