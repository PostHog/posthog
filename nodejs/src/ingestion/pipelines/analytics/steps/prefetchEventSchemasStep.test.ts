import { EventSchemaEnforcementManager } from '~/common/utils/event-schema-enforcement-manager'
import { PipelineResultType } from '~/ingestion/framework/results'
import { prefetchEventSchemasStep } from '~/ingestion/pipelines/analytics/steps/prefetchEventSchemasStep'
import { Team } from '~/types'

type TestInput = { team: Team }

function createInput(teamId: number): TestInput {
    return { team: { id: teamId } as unknown as Team }
}

describe('prefetchEventSchemasStep', () => {
    it('warms the schema cache by team id', async () => {
        const manager = {
            getSchemasForTeams: jest.fn().mockResolvedValue({}),
        } as unknown as EventSchemaEnforcementManager
        const step = prefetchEventSchemasStep<TestInput>(manager, true)

        const results = await step([createInput(3), createInput(4)])

        expect(results.map((result) => result.type)).toEqual(Array(2).fill(PipelineResultType.OK))
        expect(manager.getSchemasForTeams).toHaveBeenCalledWith([3, 4], { flush: true })
    })
})
