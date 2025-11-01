import { DateTime } from 'luxon'

import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { EventHeaders } from '../../types'
import { ok } from '../pipelines/results'
import { createValidateHistoricalMigrationStep } from './validate-historical-migration'

describe('createValidateHistoricalMigrationStep', () => {
    let headers: EventHeaders
    let step: ReturnType<typeof createValidateHistoricalMigrationStep>

    beforeEach(() => {
        headers = createTestEventHeaders({
            now: '2023-01-15T12:00:00Z',
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
            const now = DateTime.fromISO('2023-01-15T12:00:00Z')
            const timestamp = now.minus({ hours: 24 }).toISO()!
            headers.now = now.toISO()!
            headers.timestamp = timestamp

            const input = { headers }
            const result = await step(input)

            expect(result).toEqual(ok({ headers: { ...headers, historical_migration: false } }))
        })

        it('should return headers with historical_migration as true when timestamp is exactly 48 hours old', async () => {
            const now = DateTime.fromISO('2023-01-15T12:00:00Z')
            const timestamp = now.minus({ hours: 48 }).toISO()!
            headers.now = now.toISO()!
            headers.timestamp = timestamp

            const input = { headers }
            const result = await step(input)

            expect(result).toEqual(ok({ headers: { ...headers, historical_migration: true } }))
        })

        it('should return headers with historical_migration as true when timestamp is older than 48 hours (historical event)', async () => {
            const now = DateTime.fromISO('2023-01-15T12:00:00Z')
            const timestamp = now.minus({ hours: 49 }).toISO()!
            headers.now = now.toISO()!
            headers.timestamp = timestamp

            const input = { headers }
            const result = await step(input)

            expect(result).toEqual(ok({ headers: { ...headers, historical_migration: true } }))
        })

        it('should return headers with historical_migration as true when timestamp is much older than 48 hours (historical event)', async () => {
            const now = DateTime.fromISO('2023-01-15T12:00:00Z')
            const timestamp = now.minus({ days: 7 }).toISO()!
            headers.now = now.toISO()!
            headers.timestamp = timestamp

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

        it('should return headers with historical_migration as true when headers.now is invalid', async () => {
            const now = DateTime.fromISO('2023-01-15T12:00:00Z')
            headers.now = 'invalid-now'
            headers.timestamp = now.toISO()!

            const input = { headers }
            const result = await step(input)

            expect(result).toEqual(ok({ headers: { ...headers, historical_migration: true } }))
        })

        it('should return headers with historical_migration as false when timestamp is in the future', async () => {
            const now = DateTime.fromISO('2023-01-15T12:00:00Z')
            const timestamp = now.plus({ hours: 1 }).toISO()!
            headers.now = now.toISO()!
            headers.timestamp = timestamp

            const input = { headers }
            const result = await step(input)

            expect(result).toEqual(ok({ headers: { ...headers, historical_migration: false } }))
        })
    })
})
