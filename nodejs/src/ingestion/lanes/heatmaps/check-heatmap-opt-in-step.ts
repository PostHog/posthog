import { PipelineResult, drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { Team } from '~/types'

type CheckHeatmapOptInInput = {
    team: Team
}

export function createCheckHeatmapOptInStep<TInput extends CheckHeatmapOptInInput>(): ProcessingStep<TInput, TInput> {
    return function checkHeatmapOptInStep(input: TInput): Promise<PipelineResult<TInput>> {
        if (input.team.heatmaps_opt_in === false) {
            return Promise.resolve(drop('heatmap_opt_in_disabled'))
        }
        return Promise.resolve(ok(input))
    }
}
