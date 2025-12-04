import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { EventHeaders } from '../../types'
import { ok } from '../pipelines/results'
import { createValidateHistoricalMigrationStep } from './validate-historical-migration'

const HOUR_MS = 60 * 60 * 1000

describe('createValidateHistoricalMigrationStep', () => {
    let headers: EventHeaders
    let step: ReturnType<typeof createValidateHistoricalMigrationStep>

    beforeEach(() => {
        headers = createTestEventHeaders({
            now: new Date('2023-01-15T12:00:00Z'),
        })

        step = createValidateHistoricalMigrationStep()
        jest.clearAllMocks()
    })

    describe('when historical_migration header is false', () => {
        it('should return headers with historical_migration as false', async () => {
            headers.historical_migration = false
            const input = { headers }

            const result = await step(input)

            expect(result).toEqual(ok({ headers: { ...headers, historical_migration: false } }))
        })
    })

    describe('when historical_migration header is true', () => {
        beforeEach(() => {
            headers.historical_migration = true
        })

        it('should return headers with historical_migration as true when no timestamp header is set', async () => {
            const input = { headers }

            const result = await step(input)

            expect(result).toEqual(ok({ headers: { ...headers, historical_migration: true } }))
        })

        it('should return headers with historical_migration as false when timestamp is within 48 hours (recent event)', async () => {
            const now = new Date('2023-01-15T12:00:00Z')
            headers.now = now
            headers.timestamp = new Date(now.getTime() - 24 * HOUR_MS).toISOString()

            const input = { headers }
            const result = await step(input)

            expect(result).toEqual(ok({ headers: { ...headers, historical_migration: false } }))
        })

        it('should return headers with historical_migration as true when timestamp is exactly 48 hours old', async () => {
            const now = new Date('2023-01-15T12:00:00Z')
            headers.now = now
            headers.timestamp = new Date(now.getTime() - 48 * HOUR_MS).toISOString()

            const input = { headers }
            const result = await step(input)

            expect(result).toEqual(ok({ headers: { ...headers, historical_migration: true } }))
        })

        it('should return headers with historical_migration as true when timestamp is older than 48 hours (historical event)', async () => {
            const now = new Date('2023-01-15T12:00:00Z')
            headers.now = now
            headers.timestamp = new Date(now.getTime() - 49 * HOUR_MS).toISOString()

            const input = { headers }
            const result = await step(input)

            expect(result).toEqual(ok({ headers: { ...headers, historical_migration: true } }))
        })

        it('should return headers with historical_migration as true when timestamp is much older than 48 hours (historical event)', async () => {
            const now = new Date('2023-01-15T12:00:00Z')
            headers.now = now
            headers.timestamp = new Date(now.getTime() - 7 * 24 * HOUR_MS).toISOString()

            const input = { headers }
            const result = await step(input)

            expect(result).toEqual(ok({ headers: { ...headers, historical_migration: true } }))
        })

        it('should return headers with historical_migration as true when header timestamp is invalid', async () => {
            headers.timestamp = 'invalid-timestamp'

            const input = { headers }
            const result = await step(input)

            expect(result).toEqual(ok({ headers: { ...headers, historical_migration: true } }))
        })

        it('should return headers with historical_migration as true when headers.now is undefined', async () => {
            // Note: headers.now can only be undefined or a valid Date - the kafka header parser
            // only sets headers.now when the date parses successfully
            headers.now = undefined
            headers.timestamp = '2023-01-15T12:00:00Z'

            const input = { headers }
            const result = await step(input)

            expect(result).toEqual(ok({ headers: { ...headers, historical_migration: true } }))
        })

        it('should return headers with historical_migration as true when headers.now is an invalid Date', async () => {
            // Defensive test - in practice the kafka header parser won't produce invalid Dates,
            // but we should handle them gracefully if they somehow occur
            headers.now = new Date('invalid-date')
            headers.timestamp = '2023-01-15T12:00:00Z'

            const input = { headers }
            const result = await step(input)

            expect(result).toEqual(ok({ headers: { ...headers, historical_migration: true } }))
        })

        it('should return headers with historical_migration as false when timestamp is in the future', async () => {
            const now = new Date('2023-01-15T12:00:00Z')
            headers.now = now
            headers.timestamp = new Date(now.getTime() + 1 * HOUR_MS).toISOString()

            const input = { headers }
            const result = await step(input)

            expect(result).toEqual(ok({ headers: { ...headers, historical_migration: false } }))
        })
    })
})
