import { PipelineResultType } from '~/ingestion/pipelines/results'
import { Team } from '~/types'

import { prefetchPersonsStep } from '../../../../src/worker/ingestion/event-pipeline/prefetchPersonsStep'
import { PersonsStore } from '../../../../src/worker/ingestion/persons/persons-store'
import { createTestPluginEvent } from '../../../helpers/plugin-event'
import { createTestTeam } from '../../../helpers/team'

describe('prefetchPersonsStep', () => {
    let mockPersonsStore: jest.Mocked<PersonsStore>
    let team: Team

    function createMockPersonsStore(): jest.Mocked<PersonsStore> {
        return {
            prefetchPersons: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<PersonsStore>
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
    })

    describe('when enabled', () => {
        it('should prefetch persons for all events', async () => {
            const step = prefetchPersonsStep(mockPersonsStore, true)
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
            const step = prefetchPersonsStep(mockPersonsStore, true)

            const results = await step([])

            expect(results).toHaveLength(0)
            expect(mockPersonsStore.prefetchPersons).not.toHaveBeenCalled()
        })

        it('should call prefetch once for all events', async () => {
            const step = prefetchPersonsStep(mockPersonsStore, true)
            const events = [createInput('user-1'), createInput('user-2')]

            await step(events)

            expect(mockPersonsStore.prefetchPersons).toHaveBeenCalledTimes(1)
        })
    })

    describe('when disabled', () => {
        it('should not prefetch and return all events as OK', async () => {
            const step = prefetchPersonsStep(mockPersonsStore, false)
            const events = [createInput('user-1'), createInput('user-2')]

            const results = await step(events)

            expect(results).toHaveLength(2)
            expect(results.every((r) => r.type === PipelineResultType.OK)).toBe(true)
            expect(mockPersonsStore.prefetchPersons).not.toHaveBeenCalled()
        })
    })
})
