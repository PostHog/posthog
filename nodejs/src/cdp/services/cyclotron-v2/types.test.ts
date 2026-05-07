import { v7 as uuidv7 } from 'uuid'

import { CyclotronV2JobInitSchema, CyclotronV2RescheduleOptionsSchema } from './types'

describe('CyclotronV2 schema validation', () => {
    describe('personId coercion in CyclotronV2JobInitSchema', () => {
        it('accepts a valid UUID and preserves it', () => {
            const personId = uuidv7()
            const parsed = CyclotronV2JobInitSchema.parse({ teamId: 1, queueName: 'q', personId })
            expect(parsed.personId).toBe(personId)
        })

        it('coerces non-UUID strings to null (e.g. group keys from blast radius)', () => {
            const parsed = CyclotronV2JobInitSchema.parse({
                teamId: 1,
                queueName: 'q',
                personId: 'group-key-not-a-uuid',
            })
            expect(parsed.personId).toBeNull()
        })

        it.each([
            ['empty string', ''],
            ['arbitrary text', 'not-a-uuid'],
            ['nearly-uuid', '12345678-1234-1234-1234-12345678901'],
            ['numeric id', '12345'],
            ['email-like', 'user@example.com'],
        ])('coerces %s to null', (_, value) => {
            const parsed = CyclotronV2JobInitSchema.parse({ teamId: 1, queueName: 'q', personId: value })
            expect(parsed.personId).toBeNull()
        })

        it('passes through null', () => {
            const parsed = CyclotronV2JobInitSchema.parse({ teamId: 1, queueName: 'q', personId: null })
            expect(parsed.personId).toBeNull()
        })

        it('passes through undefined', () => {
            const parsed = CyclotronV2JobInitSchema.parse({ teamId: 1, queueName: 'q' })
            expect(parsed.personId).toBeUndefined()
        })

        it('accepts a UUID v4', () => {
            const personId = '550e8400-e29b-41d4-a716-446655440000'
            const parsed = CyclotronV2JobInitSchema.parse({ teamId: 1, queueName: 'q', personId })
            expect(parsed.personId).toBe(personId)
        })
    })

    describe('personId coercion in CyclotronV2RescheduleOptionsSchema', () => {
        it('accepts a valid UUID', () => {
            const personId = uuidv7()
            const parsed = CyclotronV2RescheduleOptionsSchema.parse({ personId })
            expect(parsed.personId).toBe(personId)
        })

        it('coerces non-UUID strings to null', () => {
            const parsed = CyclotronV2RescheduleOptionsSchema.parse({ personId: 'group-key' })
            expect(parsed.personId).toBeNull()
        })

        it('passes through null', () => {
            const parsed = CyclotronV2RescheduleOptionsSchema.parse({ personId: null })
            expect(parsed.personId).toBeNull()
        })
    })
})
