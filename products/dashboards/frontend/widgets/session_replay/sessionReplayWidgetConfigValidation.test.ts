import { ApiError } from 'lib/api-error'

import { sessionReplayWidgetConfigSchema } from '../../widget_types/configSchemas'
import {
    parseSessionReplayWidgetConfigApiError,
    validateSessionReplayWidgetConfigInput,
} from './sessionReplayWidgetConfigValidation'

describe('validateSessionReplayWidgetConfigInput', () => {
    it('rejects limit above 25 with inline-friendly message', () => {
        const result = validateSessionReplayWidgetConfigInput({
            limit: 30,
            orderBy: 'start_time',
            dateFrom: '-7d',
            filterTestAccounts: true,
            baseConfig: sessionReplayWidgetConfigSchema.parse({}),
        })

        expect(result.success).toBe(false)
        if (!result.success) {
            expect(result.fieldErrors.limit).toBe('Must be an integer between 1 and 25.')
        }
    })

    it('accepts valid config', () => {
        const result = validateSessionReplayWidgetConfigInput({
            limit: 10,
            orderBy: 'start_time',
            dateFrom: '-7d',
            filterTestAccounts: true,
            baseConfig: sessionReplayWidgetConfigSchema.parse({}),
        })

        expect(result.success).toBe(true)
        if (result.success) {
            expect(result.config.limit).toBe(10)
            expect(result.config.dateRange).toEqual({ date_from: '-7d' })
            expect(result.config.filterTestAccounts).toBe(true)
        }
    })

    it('accepts short date range', () => {
        const result = validateSessionReplayWidgetConfigInput({
            limit: 10,
            orderBy: 'start_time',
            dateFrom: '-1h',
            filterTestAccounts: true,
            baseConfig: sessionReplayWidgetConfigSchema.parse({}),
        })

        expect(result.success).toBe(true)
        if (result.success) {
            expect(result.config.dateRange).toEqual({ date_from: '-1h' })
        }
    })
})

describe('parseSessionReplayWidgetConfigApiError', () => {
    it('maps invalid config to zod field errors', () => {
        const error = new ApiError('limit must be an integer between 1 and 25.', 400, undefined, {
            config: 'limit must be an integer between 1 and 25.',
        })

        expect(
            parseSessionReplayWidgetConfigApiError(error, {
                limit: 30,
                orderBy: 'start_time',
                dateRange: { date_from: '-7d' },
            })
        ).toEqual({
            limit: 'Must be an integer between 1 and 25.',
        })
    })
})
