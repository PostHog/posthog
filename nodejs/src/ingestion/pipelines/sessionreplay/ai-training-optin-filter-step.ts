import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

export interface AiTrainingOptInFilterStepInput {
    team: TeamForReplay
}

/** Drops sessions whose org did not opt into AI training (fail-closed); used only by the ML mirror. */
export function createAiTrainingOptInFilterStep<T extends AiTrainingOptInFilterStepInput>(): ProcessingStep<T, T> {
    return function aiTrainingOptInFilterStep(input) {
        if (!input.team.aiTrainingOptedIn) {
            return Promise.resolve(drop('team_not_ai_training_opted_in'))
        }
        return Promise.resolve(ok(input))
    }
}
