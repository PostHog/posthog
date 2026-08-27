import { ok } from '~/ingestion/framework/results'
import { createTestEventHeaders } from '~/tests/helpers/event-headers'
import { EventHeaders } from '~/types'

import { createValidateHistoricalMigrationStep } from './validate-historical-migration'

const HOUR_MS = 60 * 60 * 1000
const NOW = new Date('2023-01-15T12:00:00Z')

// Capture sends `timestamp` as epoch milliseconds in a decimal string, so fixtures
// that use an ISO date exercise a format the step never receives.
const asHeaderTimestamp = (offsetMs: number): string => (NOW.getTime() + offsetMs).toString()

describe('createValidateHistoricalMigrationStep', () => {
    let headers: EventHeaders
    let step: ReturnType<typeof createValidateHistoricalMigrationStep>

    beforeEach(() => {
        headers = createTestEventHeaders({ now: NOW })
        step = createValidateHistoricalMigrationStep()
        jest.clearAllMocks()
    })

    it('should force historical_migration to false when the header is false', async () => {
        headers.historical_migration = false

        const result = await step({ headers })

        expect(result).toEqual(ok({ headers: { ...headers, historical_migration: false } }))
    })

    describe('when historical_migration header is true', () => {
        beforeEach(() => {
            headers.historical_migration = true
        })

        it.each([
            { age: '24 hours old', offsetMs: -24 * HOUR_MS, expected: false },
            { age: '1 hour in the future', offsetMs: HOUR_MS, expected: false },
            { age: 'exactly 48 hours old', offsetMs: -48 * HOUR_MS, expected: true },
            { age: '49 hours old', offsetMs: -49 * HOUR_MS, expected: true },
            { age: '7 days old', offsetMs: -7 * 24 * HOUR_MS, expected: true },
        ])('should resolve historical_migration to $expected for an event $age', async ({ offsetMs, expected }) => {
            headers.timestamp = asHeaderTimestamp(offsetMs)

            const result = await step({ headers })

            expect(result).toEqual(ok({ headers: { ...headers, historical_migration: expected } }))
        })

        // Keeping the flag when the age is unknown is the safe direction: an event the sender
        // declared historical stays on the historical lane instead of joining live traffic.
        it.each([
            { scenario: 'no timestamp header', patch: {} },
            { scenario: 'a non-numeric timestamp header', patch: { timestamp: 'invalid-timestamp' } },
            { scenario: 'no now header', patch: { timestamp: asHeaderTimestamp(0), now: undefined } },
            {
                scenario: 'an unparseable now header',
                patch: { timestamp: asHeaderTimestamp(0), now: new Date('invalid-date') },
            },
        ])('should keep historical_migration as true with $scenario', async ({ patch }) => {
            Object.assign(headers, patch)

            const result = await step({ headers })

            expect(result).toEqual(ok({ headers: { ...headers, historical_migration: true } }))
        })
    })
})
