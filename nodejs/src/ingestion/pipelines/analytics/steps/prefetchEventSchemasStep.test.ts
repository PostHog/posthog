import { EventSchemaEnforcementManager } from '~/common/utils/event-schema-enforcement-manager'
import { logger } from '~/common/utils/logger'
import { PipelineResultType, isOkResult } from '~/ingestion/framework/results'
import { prefetchEventSchemasStep } from '~/ingestion/pipelines/analytics/steps/prefetchEventSchemasStep'
import { Team } from '~/types'

type TestInput = { team: Team }

function createInput(teamId: number): TestInput {
    return { team: { id: teamId } as unknown as Team }
}

describe('prefetchEventSchemasStep', () => {
    let manager: EventSchemaEnforcementManager

    beforeEach(() => {
        manager = { getSchemasForTeams: jest.fn().mockResolvedValue({}) } as unknown as EventSchemaEnforcementManager
    })

    it('warms the schema cache once per distinct team and passes events through', async () => {
        const step = prefetchEventSchemasStep<TestInput>(manager, true)

        const results = await step([createInput(3), createInput(4), createInput(3)])

        expect(results.map((result) => result.type)).toEqual(Array(3).fill(PipelineResultType.OK))
        expect(results.filter(isOkResult).map((result) => result.value.team.id)).toEqual([3, 4, 3])
        expect(manager.getSchemasForTeams).toHaveBeenCalledTimes(1)
        expect(manager.getSchemasForTeams).toHaveBeenCalledWith([3, 4])
    })

    it('passes events through without prefetching when disabled', async () => {
        const step = prefetchEventSchemasStep<TestInput>(manager, false)

        const results = await step([createInput(3)])

        expect(results.map((result) => result.type)).toEqual([PipelineResultType.OK])
        expect(manager.getSchemasForTeams).not.toHaveBeenCalled()
    })

    it('keeps events flowing and warns when the warm-up load fails on a retriable error', async () => {
        jest.mocked(manager.getSchemasForTeams).mockRejectedValue(
            Object.assign(new Error('postgres down'), { isRetriable: true })
        )
        const step = prefetchEventSchemasStep<TestInput>(manager, true)

        const results = await step([createInput(3)])
        await new Promise((resolve) => setImmediate(resolve))

        expect(results.map((result) => result.type)).toEqual([PipelineResultType.OK])
        expect(logger.warn).toHaveBeenCalledWith(
            '⚠️',
            'prefetchEventSchemas failed on a retriable error',
            expect.objectContaining({ error: expect.stringContaining('postgres down') })
        )
    })
})
