import { Team } from '../../types'
import { PipelineResult, drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

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
