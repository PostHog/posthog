import { createTestTeam } from '../../../tests/helpers/team'
import { Team } from '../../types'
import { PipelineResultType } from '../pipelines/results'
import { createCheckHeatmapOptInStep } from './check-heatmap-opt-in-step'

interface TestInput {
    team: Team
    extraField: string
}

describe('createCheckHeatmapOptInStep', () => {
    it.each([
        { heatmaps_opt_in: true, expected: PipelineResultType.OK },
        { heatmaps_opt_in: null, expected: PipelineResultType.OK },
        { heatmaps_opt_in: false, expected: PipelineResultType.DROP },
    ])('should return $expected when heatmaps_opt_in=$heatmaps_opt_in', async ({ heatmaps_opt_in, expected }) => {
        const step = createCheckHeatmapOptInStep<TestInput>()
        const team = createTestTeam({ heatmaps_opt_in })
        const input: TestInput = { team, extraField: 'preserved' }

        const result = await step(input)

        expect(result.type).toBe(expected)
        if (result.type === PipelineResultType.OK) {
            expect(result.value).toBe(input)
            expect(result.value.extraField).toBe('preserved')
        }
        if (result.type === PipelineResultType.DROP) {
            expect(result.reason).toBe('heatmap_opt_in_disabled')
        }
    })
})
