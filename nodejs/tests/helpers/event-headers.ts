import { EventHeaders } from '../../src/types'

/**
 * Helper function to create EventHeaders for tests with sensible defaults.
 * Only required fields need to be set by default, optional fields can be overridden.
 *
 * @param overrides - Partial EventHeaders to override defaults
 * @returns Complete EventHeaders object
 *
 * @example
 * // Create headers with just defaults
 * const headers = createTestEventHeaders()
 *
 * @example
 * // Override specific fields
 * const headers = createTestEventHeaders({
 *     token: 'custom-token',
 *     distinct_id: 'user-123',
 *     historical_migration: true
 * })
 */
export function createTestEventHeaders(overrides: Partial<EventHeaders> = {}): EventHeaders {
    return {
        force_disable_person_processing: false,
        historical_migration: false,
        ...overrides,
    }
}
