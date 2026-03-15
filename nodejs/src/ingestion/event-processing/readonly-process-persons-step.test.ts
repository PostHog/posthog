import { DateTime } from 'luxon'

import { createTestPerson } from '../../../tests/helpers/person'
import { createTestPluginEvent } from '../../../tests/helpers/plugin-event'
import { createTestTeam } from '../../../tests/helpers/team'
import { InternalPerson } from '../../types'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { isOkResult } from '../pipelines/results'
import { createReadonlyProcessPersonsStep } from './readonly-process-persons-step'

describe('readonly-process-persons-step', () => {
    let mockPersonsStore: jest.Mocked<Pick<PersonsStore, 'fetchForChecking'>>

    const team = createTestTeam()
    const timestamp = DateTime.utc(2023, 6, 15)

    beforeEach(() => {
        mockPersonsStore = {
            fetchForChecking: jest.fn().mockResolvedValue(null),
        }
    })

    function createInternalPerson(overrides: Partial<InternalPerson> = {}): InternalPerson {
        return {
            id: '42',
            team_id: team.id,
            uuid: 'person-uuid-123',
            properties: {},
            created_at: DateTime.utc(2023, 1, 1),
            is_user_id: null,
            is_identified: false,
            version: 0,
            last_seen_at: null,
            properties_last_updated_at: {},
            properties_last_operation: null,
            ...overrides,
        }
    }

    it('returns the person with merged properties when found in the store', async () => {
        const existingPerson = createInternalPerson({ properties: { email: 'test@example.com' } })
        mockPersonsStore.fetchForChecking.mockResolvedValue(existingPerson)

        const step = createReadonlyProcessPersonsStep(mockPersonsStore as unknown as PersonsStore)
        const event = createTestPluginEvent({
            distinct_id: 'user-1',
            properties: { $set: { name: 'Alice' } },
        })
        const result = await step({ normalizedEvent: event, team, timestamp })

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }
        expect(result.value.person).toEqual({
            team_id: team.id,
            uuid: 'person-uuid-123',
            properties: { email: 'test@example.com', name: 'Alice' },
            created_at: DateTime.utc(2023, 1, 1),
        })
        expect(mockPersonsStore.fetchForChecking).toHaveBeenCalledWith(team.id, 'user-1')
    })

    it('returns personPropertyUpdates with hasChanges=true when event has $set changes', async () => {
        const existingPerson = createInternalPerson({ properties: { email: 'test@example.com' } })
        mockPersonsStore.fetchForChecking.mockResolvedValue(existingPerson)

        const step = createReadonlyProcessPersonsStep(mockPersonsStore as unknown as PersonsStore)
        const event = createTestPluginEvent({
            properties: { $set: { name: 'Alice' } },
        })
        const result = await step({ normalizedEvent: event, team, timestamp })

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }
        expect(result.value.personPropertyUpdates?.hasChanges).toBe(true)
        expect(result.value.personPropertyUpdates?.toSet).toEqual({ name: 'Alice' })
    })

    it('returns personPropertyUpdates with hasChanges=false when no property changes', async () => {
        const existingPerson = createInternalPerson({ properties: { name: 'Alice' } })
        mockPersonsStore.fetchForChecking.mockResolvedValue(existingPerson)

        const step = createReadonlyProcessPersonsStep(mockPersonsStore as unknown as PersonsStore)
        const event = createTestPluginEvent({ properties: {} })
        const result = await step({ normalizedEvent: event, team, timestamp })

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }
        expect(result.value.personPropertyUpdates?.hasChanges).toBe(false)
    })

    it('applies $set_once only for new properties', async () => {
        const existingPerson = createInternalPerson({ properties: { name: 'Alice' } })
        mockPersonsStore.fetchForChecking.mockResolvedValue(existingPerson)

        const step = createReadonlyProcessPersonsStep(mockPersonsStore as unknown as PersonsStore)
        const event = createTestPluginEvent({
            properties: { $set_once: { name: 'Bob', role: 'admin' } },
        })
        const result = await step({ normalizedEvent: event, team, timestamp })

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }
        // name stays as Alice ($set_once skips existing), role is new
        expect(result.value.person!.properties).toEqual({ name: 'Alice', role: 'admin' })
    })

    it('applies $unset to remove properties', async () => {
        const existingPerson = createInternalPerson({ properties: { name: 'Alice', email: 'a@b.com' } })
        mockPersonsStore.fetchForChecking.mockResolvedValue(existingPerson)

        const step = createReadonlyProcessPersonsStep(mockPersonsStore as unknown as PersonsStore)
        const event = createTestPluginEvent({
            properties: { $unset: ['email'] },
        })
        const result = await step({ normalizedEvent: event, team, timestamp })

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }
        expect(result.value.person!.properties).toEqual({ name: 'Alice' })
    })

    it('returns undefined person when not found in the store', async () => {
        mockPersonsStore.fetchForChecking.mockResolvedValue(null)

        const step = createReadonlyProcessPersonsStep(mockPersonsStore as unknown as PersonsStore)
        const event = createTestPluginEvent({ distinct_id: 'unknown-user' })
        const result = await step({ normalizedEvent: event, team, timestamp })

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }
        expect(result.value.person).toBeUndefined()
        expect(result.value.personPropertyUpdates).toBeUndefined()
    })

    it('defaults null properties to empty object before merging', async () => {
        const existingPerson = createInternalPerson({ properties: null as any })
        mockPersonsStore.fetchForChecking.mockResolvedValue(existingPerson)

        const step = createReadonlyProcessPersonsStep(mockPersonsStore as unknown as PersonsStore)
        const event = createTestPluginEvent({
            properties: { $set: { name: 'Alice' } },
        })
        const result = await step({ normalizedEvent: event, team, timestamp })

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }
        expect(result.value.person!.properties).toEqual({ name: 'Alice' })
    })

    it('short-circuits with personlessPerson when set without force_upgrade', async () => {
        const personlessPerson = createTestPerson({ uuid: 'personless-uuid', properties: {} })

        const step = createReadonlyProcessPersonsStep(mockPersonsStore as unknown as PersonsStore)
        const event = createTestPluginEvent()
        const result = await step({ normalizedEvent: event, team, timestamp, personlessPerson })

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }
        expect(result.value.person).toBe(personlessPerson)
        expect(result.value.personPropertyUpdates).toBeUndefined()
        expect(mockPersonsStore.fetchForChecking).not.toHaveBeenCalled()
    })

    it('does not short-circuit when personlessPerson has force_upgrade', async () => {
        const personlessPerson = createTestPerson({ uuid: 'personless-uuid', force_upgrade: true })
        const existingPerson = createInternalPerson({ properties: { email: 'test@example.com' } })
        mockPersonsStore.fetchForChecking.mockResolvedValue(existingPerson)

        const step = createReadonlyProcessPersonsStep(mockPersonsStore as unknown as PersonsStore)
        const event = createTestPluginEvent({ properties: { $set: { name: 'Alice' } } })
        const result = await step({ normalizedEvent: event, team, timestamp, personlessPerson })

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }
        expect(result.value.person!.force_upgrade).toBe(true)
        expect(result.value.person!.properties).toEqual({ email: 'test@example.com', name: 'Alice' })
        expect(mockPersonsStore.fetchForChecking).toHaveBeenCalled()
    })

    it('produces no side effects', async () => {
        const existingPerson = createInternalPerson({ properties: { foo: 'bar' } })
        mockPersonsStore.fetchForChecking.mockResolvedValue(existingPerson)

        const step = createReadonlyProcessPersonsStep(mockPersonsStore as unknown as PersonsStore)
        const event = createTestPluginEvent({ properties: { $set: { foo: 'baz' } } })
        const result = await step({ normalizedEvent: event, team, timestamp })

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }
        expect(result.sideEffects).toEqual([])
    })
})
