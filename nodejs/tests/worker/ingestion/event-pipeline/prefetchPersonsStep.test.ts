import { PersonsStoreForBatch } from '~/ingestion/common/persons/persons-store-for-batch'
import { PipelineResultType } from '~/ingestion/framework/results'
import { prefetchPersonsStep } from '~/ingestion/pipelines/analytics/steps/prefetchPersonsStep'
import { Team } from '~/types'

import { createTestPluginEvent } from '../../../helpers/plugin-event'
import { createTestTeam } from '../../../helpers/team'

describe('prefetchPersonsStep', () => {
    let mockPersonsStore: jest.Mocked<PersonsStoreForBatch>
    let team: Team

    function createMockPersonsStore(): jest.Mocked<PersonsStoreForBatch> {
        return {
            prefetchPersons: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<PersonsStoreForBatch>
    }

    beforeEach(() => {
        team = createTestTeam()
        mockPersonsStore = createMockPersonsStore()
    })

    const createInput = (distinctId: string, overrides: { team?: Team } = {}) => ({
        event: createTestPluginEvent({
            distinct_id: distinctId,
            team_id: (overrides.team ?? team).id,
        }),
        team: overrides.team ?? team,
        personsStoreForBatch: mockPersonsStore,
    })

    describe('when enabled', () => {
        it('should prefetch persons for all events', async () => {
            const step = prefetchPersonsStep(true)
            const events = [createInput('user-1'), createInput('user-2'), createInput('user-3')]

            const results = await step(events)

            expect(results).toHaveLength(3)
            expect(results.every((r) => r.type === PipelineResultType.OK)).toBe(true)
            expect(mockPersonsStore.prefetchPersons).toHaveBeenCalledWith([
                { teamId: team.id, distinctId: 'user-1' },
                { teamId: team.id, distinctId: 'user-2' },
                { teamId: team.id, distinctId: 'user-3' },
            ])
        })

        it('should not call prefetch for empty batch', async () => {
            const step = prefetchPersonsStep(true)

            const results = await step([])

            expect(results).toHaveLength(0)
            expect(mockPersonsStore.prefetchPersons).not.toHaveBeenCalled()
        })

        it('should call prefetch once for all events', async () => {
            const step = prefetchPersonsStep(true)
            const events = [createInput('user-1'), createInput('user-2')]

            await step(events)

            expect(mockPersonsStore.prefetchPersons).toHaveBeenCalledTimes(1)
        })
    })

    describe('when disabled', () => {
        it('should not prefetch and return all events as OK', async () => {
            const step = prefetchPersonsStep(false)
            const events = [createInput('user-1'), createInput('user-2')]

            const results = await step(events)

            expect(results).toHaveLength(2)
            expect(results.every((r) => r.type === PipelineResultType.OK)).toBe(true)
            expect(mockPersonsStore.prefetchPersons).not.toHaveBeenCalled()
        })
    })
})
