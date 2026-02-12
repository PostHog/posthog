import { ok } from '~/ingestion/pipelines/results'
import { createTestEventHeaders } from '~/tests/helpers/event-headers'
import { createTestPipelineEvent } from '~/tests/helpers/pipeline-event'
import { createTestTeam } from '~/tests/helpers/team'

import { PersonsStore } from '../persons/persons-store'
import { prefetchPersonsStep } from './prefetchPersonsStep'

describe('prefetchPersonsStep', () => {
    let personsStore: PersonsStore
    let prefetchPersonsMock: jest.Mock

    beforeEach(() => {
        prefetchPersonsMock = jest.fn().mockResolvedValue(undefined)
        personsStore = {
            prefetchPersons: prefetchPersonsMock,
        } as unknown as PersonsStore
    })

    it('should prefetch persons when enabled and force_disable_person_processing is false', async () => {
        const step = prefetchPersonsStep(personsStore, true)
        const team = createTestTeam()
        const event = createTestPipelineEvent({ distinct_id: 'user-123' })
        const headers = createTestEventHeaders({ force_disable_person_processing: false })

        const input = [{ event, team, headers }]
        const result = await step(input)

        expect(result).toEqual([ok(input[0])])
        expect(prefetchPersonsMock).toHaveBeenCalledWith([{ teamId: team.id, distinctId: 'user-123' }])
        expect(prefetchPersonsMock).toHaveBeenCalledTimes(1)
    })

    it('should NOT prefetch persons when force_disable_person_processing is true', async () => {
        const step = prefetchPersonsStep(personsStore, true)
        const team = createTestTeam()
        const event = createTestPipelineEvent({ distinct_id: 'user-123' })
        const headers = createTestEventHeaders({ force_disable_person_processing: true })

        const input = [{ event, team, headers }]
        const result = await step(input)

        expect(result).toEqual([ok(input[0])])
        expect(prefetchPersonsMock).not.toHaveBeenCalled()
    })

    it('should filter out events with force_disable_person_processing in mixed batch', async () => {
        const step = prefetchPersonsStep(personsStore, true)
        const team = createTestTeam()

        const event1 = createTestPipelineEvent({ distinct_id: 'user-1' })
        const headers1 = createTestEventHeaders({ force_disable_person_processing: false })

        const event2 = createTestPipelineEvent({ distinct_id: 'user-2' })
        const headers2 = createTestEventHeaders({ force_disable_person_processing: true })

        const event3 = createTestPipelineEvent({ distinct_id: 'user-3' })
        const headers3 = createTestEventHeaders({ force_disable_person_processing: false })

        const input = [
            { event: event1, team, headers: headers1 },
            { event: event2, team, headers: headers2 },
            { event: event3, team, headers: headers3 },
        ]

        const result = await step(input)

        expect(result).toEqual([ok(input[0]), ok(input[1]), ok(input[2])])
        expect(prefetchPersonsMock).toHaveBeenCalledWith([
            { teamId: team.id, distinctId: 'user-1' },
            { teamId: team.id, distinctId: 'user-3' },
        ])
        expect(prefetchPersonsMock).toHaveBeenCalledTimes(1)
    })

    it('should NOT prefetch persons when disabled globally', async () => {
        const step = prefetchPersonsStep(personsStore, false)
        const team = createTestTeam()
        const event = createTestPipelineEvent({ distinct_id: 'user-123' })
        const headers = createTestEventHeaders({ force_disable_person_processing: false })

        const input = [{ event, team, headers }]
        const result = await step(input)

        expect(result).toEqual([ok(input[0])])
        expect(prefetchPersonsMock).not.toHaveBeenCalled()
    })

    it('should NOT call prefetch when all events have force_disable_person_processing', async () => {
        const step = prefetchPersonsStep(personsStore, true)
        const team = createTestTeam()

        const event1 = createTestPipelineEvent({ distinct_id: 'user-1' })
        const headers1 = createTestEventHeaders({ force_disable_person_processing: true })

        const event2 = createTestPipelineEvent({ distinct_id: 'user-2' })
        const headers2 = createTestEventHeaders({ force_disable_person_processing: true })

        const input = [
            { event: event1, team, headers: headers1 },
            { event: event2, team, headers: headers2 },
        ]

        const result = await step(input)

        expect(result).toEqual([ok(input[0]), ok(input[1])])
        expect(prefetchPersonsMock).not.toHaveBeenCalled()
    })

    it('should handle empty batch', async () => {
        const step = prefetchPersonsStep(personsStore, true)
        const input: any[] = []

        const result = await step(input)

        expect(result).toEqual([])
        expect(prefetchPersonsMock).not.toHaveBeenCalled()
    })
})
