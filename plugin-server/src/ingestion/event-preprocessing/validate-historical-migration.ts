import { DateTime } from 'luxon'

import { EventHeaders } from '../../types'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

const HISTORICAL_MIGRATION_MIN_AGE_HOURS = 48

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

    // Parse the timestamp header and now timestamp
    const headerTimestamp = DateTime.fromISO(headers.timestamp)
    const now = DateTime.fromISO(headers.now)

    // If either timestamp is invalid, accept the flag as-is (let other validation handle it)
    if (!headerTimestamp.isValid || !now.isValid) {
        return headers
    }

    // Calculate age in hours
    const ageInHours = now.diff(headerTimestamp, 'hours').hours

    // Only accept if timestamp is at least 48 hours old (historical events)
    const historicalMigration = ageInHours >= HISTORICAL_MIGRATION_MIN_AGE_HOURS

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
