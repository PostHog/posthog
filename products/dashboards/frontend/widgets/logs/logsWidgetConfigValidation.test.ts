import { ApiError } from 'lib/api-error'

import {
    LOGS_DEFAULT_DATE_FROM,
    parseLogsWidgetConfig,
    parseLogsWidgetConfigApiError,
    patchLogsWidgetFilterFields,
    validateLogsWidgetConfigInput,
} from './logsWidgetConfigValidation'

describe('logsWidgetConfigValidation', () => {
    it('parses defaults for an empty config', () => {
        const config = parseLogsWidgetConfig({})
        expect(config.limit).toBe(50)
        expect(config.orderBy).toBe('latest')
        expect(config.wrapLines).toBe(false)
        expect(config.timezone).toBe('UTC')
        expect(config.severityLevels ?? []).toEqual([])
        expect(config.serviceNames ?? []).toEqual([])
    })

    it('patches on-tile filter fields without touching the date range', () => {
        const base = { dateRange: { date_from: '-24h' }, limit: 50, orderBy: 'latest' }
        const patched = patchLogsWidgetFilterFields(base, {
            severityLevels: ['error', 'warn'],
            serviceNames: ['api'],
            orderBy: 'earliest',
        })
        expect(patched.severityLevels).toEqual(['error', 'warn'])
        expect(patched.serviceNames).toEqual(['api'])
        expect(patched.orderBy).toBe('earliest')
        expect(patched.dateRange?.date_from).toBe('-24h')
    })

    it('clearing severity levels persists an empty list', () => {
        const base = { severityLevels: ['error'], serviceNames: ['api'] }
        const patched = patchLogsWidgetFilterFields(base, { severityLevels: [] })
        expect(patched.severityLevels).toEqual([])
        expect(patched.serviceNames).toEqual(['api'])
    })

    it('sets and clears the saved view id', () => {
        const withView = patchLogsWidgetFilterFields({}, { savedViewId: 'abc123' })
        expect(withView.savedViewId).toBe('abc123')
        // An explicit null clears it; an omitted key would have preserved it.
        const cleared = patchLogsWidgetFilterFields(withView, { savedViewId: null })
        expect(cleared.savedViewId ?? null).toBeNull()
        const preserved = patchLogsWidgetFilterFields(withView, { orderBy: 'earliest' })
        expect(preserved.savedViewId).toBe('abc123')
    })

    it('falls back to the default date range when none is set', () => {
        const patched = patchLogsWidgetFilterFields({}, { orderBy: 'earliest' })
        expect(patched.dateRange?.date_from).toBe(LOGS_DEFAULT_DATE_FROM)
    })

    it('validates a well-formed form input', () => {
        const result = validateLogsWidgetConfigInput({
            limit: 15,
            wrapLines: true,
            timezone: 'local',
            dateFrom: '-24h',
            baseConfig: parseLogsWidgetConfig({}),
        })
        expect(result.success).toBe(true)
        if (result.success) {
            expect(result.config.limit).toBe(15)
            expect(result.config.wrapLines).toBe(true)
            expect(result.config.timezone).toBe('local')
            expect(result.config.dateRange?.date_from).toBe('-24h')
        }
    })

    it('accepts a limit at the cap', () => {
        const result = validateLogsWidgetConfigInput({
            limit: 100,
            wrapLines: false,
            timezone: 'UTC',
            dateFrom: '-1h',
            baseConfig: parseLogsWidgetConfig({}),
        })
        expect(result.success).toBe(true)
    })

    it('rejects a limit above the cap', () => {
        const result = validateLogsWidgetConfigInput({
            limit: 101,
            wrapLines: false,
            timezone: 'UTC',
            dateFrom: '-1h',
            baseConfig: parseLogsWidgetConfig({}),
        })
        expect(result.success).toBe(false)
        if (!result.success) {
            expect(result.fieldErrors.limit).toBeTruthy()
        }
    })

    it('maps an API error to a field error', () => {
        const error = new ApiError('limit too big', 400, undefined, { config: 'limit too big' })
        const fieldErrors = parseLogsWidgetConfigApiError(error, { limit: 101, orderBy: 'latest' })
        expect(fieldErrors?.limit).toBeTruthy()
    })

    it('ignores non-API errors', () => {
        expect(parseLogsWidgetConfigApiError(new Error('boom'), {})).toBeNull()
    })
})
