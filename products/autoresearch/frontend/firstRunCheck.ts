import { LemonDialog } from '@posthog/lemon-ui'

import { autoresearchValidateCreate } from './generated/api'
import {
    AutoresearchPipelineApi,
    ValidatePipelineRequestApi,
    ValidatePipelineResponseApi,
} from './generated/api.schemas'

/** A draft that never trained has a definition no check may have passed, because the create form saves drafts without one. */
export function needsFirstRunCheck(pipeline: AutoresearchPipelineApi): boolean {
    return pipeline.status === 'draft' && pipeline.training_run_count === 0
}

export async function runFirstRunCheck(
    teamId: string,
    pipeline: AutoresearchPipelineApi
): Promise<ValidatePipelineResponseApi> {
    return await autoresearchValidateCreate(teamId, {
        target_event: pipeline.target_event,
        target_definition: pipeline.target_definition as ValidatePipelineRequestApi['target_definition'],
        horizon_days: pipeline.horizon_days,
        training_lookback_days: pipeline.training_lookback_days,
        training_population: pipeline.training_population,
        inference_population: pipeline.inference_population,
    })
}

/** Why the check did not pass, or null when it did. */
export function firstRunCheckProblem(validation: ValidatePipelineResponseApi): string | null {
    if (validation.error_code === 'too_expensive') {
        return "The check ran out of time on this project's data, so it couldn't tell if there is enough data to learn from. Narrowing who the model predicts for, for example to people who did a specific event, makes the check and training cheaper."
    }
    if (validation.error) {
        return `Couldn't check this model: ${validation.error}`
    }
    if (validation.can_proceed) {
        return null
    }
    const failures = validation.warnings.filter((w) => w.severity === 'error').map((w) => w.message)
    return failures.length > 0 ? failures.join(' ') : "This model didn't pass the check."
}

export function confirmTrainingWithoutCheck(problem: string, onConfirm: () => void): void {
    LemonDialog.open({
        title: 'Start training without a passing check?',
        description: `${problem} The run still counts against this project's daily training limit.`,
        primaryButton: {
            children: 'Start training anyway',
            onClick: onConfirm,
            'data-attr': 'autoresearch-first-run-check-confirm',
        },
        secondaryButton: { children: 'Cancel' },
    })
}
