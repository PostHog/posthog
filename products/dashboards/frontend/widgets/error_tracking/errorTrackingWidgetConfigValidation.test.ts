import { ApiError } from 'lib/api-error'

import { errorTrackingWidgetConfigSchema } from '../../widget_types/configSchemas'
import {
    parseErrorTrackingWidgetConfigApiError,
    validateErrorTrackingWidgetConfigInput,
} from './errorTrackingWidgetConfigValidation'

describe('validateErrorTrackingWidgetConfigInput', () => {
    it('rejects limit above 25 with inline-friendly message', () => {
        const result = validateErrorTrackingWidgetConfigInput({
            limit: 30,
            orderBy: 'occurrences',
            dateFrom: '-7d',
            filterTestAccounts: true,
            baseConfig: {},
        })

        expect(result.success).toBe(false)
        if (!result.success) {
            expect(result.fieldErrors.limit).toBe('Must be an integer between 1 and 25.')
        }
    })

    it('accepts valid config without filterTestAccounts', () => {
        const result = validateErrorTrackingWidgetConfigInput({
            limit: 10,
            orderBy: 'occurrences',
            dateFrom: '-7d',
            filterTestAccounts: true,
            baseConfig: {},
        })

        expect(result.success).toBe(true)
        if (result.success) {
            expect(result.config.limit).toBe(10)
            expect(result.config.dateRange).toEqual({ date_from: '-7d' })
            expect(result.config.filterTestAccounts).toBe(true)
        }
    })

    it('omits filterTestAccounts when not provided in config', () => {
        const result = errorTrackingWidgetConfigSchema.safeParse({
            limit: 10,
            orderBy: 'occurrences',
            dateRange: { date_from: '-7d' },
        })

        expect(result.success).toBe(true)
        if (result.success) {
            expect(result.data.filterTestAccounts).toBeUndefined()
        }
    })

    it('accepts short date range', () => {
        const result = validateErrorTrackingWidgetConfigInput({
            limit: 10,
            orderBy: 'occurrences',
            dateFrom: '-1h',
            filterTestAccounts: true,
            baseConfig: {},
        })

        expect(result.success).toBe(true)
        if (result.success) {
            expect(result.config.dateRange).toEqual({ date_from: '-1h' })
        }
    })
})

describe('parseErrorTrackingWidgetConfigApiError', () => {
    it('maps config limit API error to limit field', () => {
        const error = new ApiError('limit must be an integer between 1 and 25.', 400, undefined, {
            config: 'limit must be an integer between 1 and 25.',
        })

        expect(parseErrorTrackingWidgetConfigApiError(error)).toEqual({
            limit: 'Must be an integer between 1 and 25.',
        })
    })
})
