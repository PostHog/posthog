import { v7 as uuidv7 } from 'uuid'

import { CyclotronV2JobInitSchema, CyclotronV2RescheduleOptionsSchema } from './types'

describe('CyclotronV2 schema validation', () => {
    describe('personId in CyclotronV2JobInitSchema', () => {
        it('accepts a valid UUID and preserves it', () => {
            const personId = uuidv7()
            const parsed = CyclotronV2JobInitSchema.parse({ teamId: 1, queueName: 'q', personId })
            expect(parsed.personId).toBe(personId)
        })

        it.each([
            ['arbitrary text', 'group-key-not-a-uuid'],
            ['empty string', ''],
            ['nearly-uuid', '12345678-1234-1234-1234-12345678901'],
            ['numeric id', '12345'],
            ['email-like', 'user@example.com'],
        ])('passes %s through unchanged', (_, value) => {
            const parsed = CyclotronV2JobInitSchema.parse({ teamId: 1, queueName: 'q', personId: value })
            expect(parsed.personId).toBe(value)
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

    describe('personId in CyclotronV2RescheduleOptionsSchema', () => {
        it('accepts a valid UUID', () => {
            const personId = uuidv7()
            const parsed = CyclotronV2RescheduleOptionsSchema.parse({ personId })
            expect(parsed.personId).toBe(personId)
        })

        it('passes a non-UUID string through unchanged', () => {
            const parsed = CyclotronV2RescheduleOptionsSchema.parse({ personId: 'group-key' })
            expect(parsed.personId).toBe('group-key')
        })

        it('passes through null', () => {
            const parsed = CyclotronV2RescheduleOptionsSchema.parse({ personId: null })
            expect(parsed.personId).toBeNull()
        })
    })
})
