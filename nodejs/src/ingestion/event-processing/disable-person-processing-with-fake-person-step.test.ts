import { DateTime } from 'luxon'

import { Team } from '../../types'
import { uuidFromDistinctId } from '../../worker/ingestion/person-uuid'
import { isOkResult } from '../pipelines/results'
import { createDisablePersonProcessingWithFakePersonStep } from './disable-person-processing-with-fake-person-step'

describe('createDisablePersonProcessingWithFakePersonStep', () => {
    const team = { id: 42, project_id: 42 } as Team

    const step = createDisablePersonProcessingWithFakePersonStep()

    it('should set processPerson to false', async () => {
        const input = { team, event: { distinct_id: 'user-1' }, headers: {} }
        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value.processPerson).toBe(false)
        }
    })

    it('should provide a deterministic fake person', async () => {
        const input = { team, event: { distinct_id: 'user-1' }, headers: {} }
        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value.person.team_id).toBe(42)
            expect(result.value.person.properties).toEqual({})
            expect(result.value.person.uuid).toBe(uuidFromDistinctId(42, 'user-1'))
            expect(result.value.person.created_at).toEqual(DateTime.utc(1970, 1, 1, 0, 0, 5))
        }
    })

    it('should produce the same person uuid for the same team and distinct_id', async () => {
        const input1 = { team, event: { distinct_id: 'user-1' }, headers: {} }
        const input2 = { team, event: { distinct_id: 'user-1' }, headers: {} }

        const result1 = await step(input1)
        const result2 = await step(input2)

        expect(isOkResult(result1)).toBe(true)
        expect(isOkResult(result2)).toBe(true)
        if (isOkResult(result1) && isOkResult(result2)) {
            expect(result1.value.person.uuid).toBe(result2.value.person.uuid)
        }
    })

    it('should produce different person uuids for different distinct_ids', async () => {
        const input1 = { team, event: { distinct_id: 'user-1' }, headers: {} }
        const input2 = { team, event: { distinct_id: 'user-2' }, headers: {} }

        const result1 = await step(input1)
        const result2 = await step(input2)

        expect(isOkResult(result1)).toBe(true)
        expect(isOkResult(result2)).toBe(true)
        if (isOkResult(result1) && isOkResult(result2)) {
            expect(result1.value.person.uuid).not.toBe(result2.value.person.uuid)
        }
    })

    it('should preserve existing input fields', async () => {
        const input = { team, event: { distinct_id: 'user-1' } }
        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value.team).toBe(team)
            expect(result.value.event).toEqual({ distinct_id: 'user-1' })
        }
    })
})
