import { EventHeaders } from '../../types'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

const HISTORICAL_MIGRATION_MIN_AGE_MS = 48 * 60 * 60 * 1000 // 48 hours in milliseconds

type ValidateHistoricalMigrationInput = { headers: EventHeaders }
type ValidateHistoricalMigrationOutput = { headers: EventHeaders }

function validateHistoricalMigrationHeader(headers: EventHeaders): EventHeaders {
    // If header is not set to true, ensure it's false
    if (!headers.historical_migration) {
        return { ...headers, historical_migration: false }
    }

    // If no timestamp header or no now header, accept the historical migration flag as-is
    if (!headers.timestamp || !headers.now) {
        return headers
    }

    // Parse the timestamp header
    const headerTimestampMs = Date.parse(headers.timestamp)
    const nowMs = headers.now.getTime()

    // If either timestamp is invalid, accept the flag as-is (let other validation handle it)
    if (isNaN(headerTimestampMs) || isNaN(nowMs)) {
        return headers
    }

    // Only accept if timestamp is at least 48 hours old (historical events)
    const ageMs = nowMs - headerTimestampMs
    const historicalMigration = ageMs >= HISTORICAL_MIGRATION_MIN_AGE_MS

    return { ...headers, historical_migration: historicalMigration }
}

export function createValidateHistoricalMigrationStep<T extends ValidateHistoricalMigrationInput>(): ProcessingStep<
    T,
    T & ValidateHistoricalMigrationOutput
> {
    return async function validateHistoricalMigrationStep(input) {
        const validatedHeaders = validateHistoricalMigrationHeader(input.headers)

        return Promise.resolve(ok({ ...input, headers: validatedHeaders }))
    }
}
