import { ApiError } from 'lib/api-error'

import { PropertyOperator } from '~/types'

import { errorTrackingWidgetConfigSchema } from '../../generated/widget-configs.zod'
import {
    ERROR_TRACKING_WIDGET_FORM_FIELD_NAMES,
    parseErrorTrackingWidgetConfigApiError,
    patchErrorTrackingWidgetFilterFields,
    validateErrorTrackingWidgetConfigInput,
} from './errorTrackingWidgetConfigValidation'

describe('errorTrackingWidgetConfigValidation', () => {
    it('form picked fields exist on the generated config schema', () => {
        const shape = errorTrackingWidgetConfigSchema.shape
        for (const field of ERROR_TRACKING_WIDGET_FORM_FIELD_NAMES) {
            expect(shape).toHaveProperty(field)
        }
    })
})

describe('validateErrorTrackingWidgetConfigInput', () => {
    it('rejects limit above 25 with inline-friendly message', () => {
        const result = validateErrorTrackingWidgetConfigInput({
            limit: 30,
            orderBy: 'occurrences',
            orderDirection: 'DESC',
            filterTestAccounts: true,
            baseConfig: errorTrackingWidgetConfigSchema.parse({}),
        })

        expect(result.success).toBe(false)
        if (!result.success) {
            expect(result.fieldErrors.limit).toBe('Too big: expected number to be <=25')
        }
    })

    it('accepts valid config', () => {
        const result = validateErrorTrackingWidgetConfigInput({
            limit: 10,
            orderBy: 'occurrences',
            orderDirection: 'DESC',
            filterTestAccounts: true,
            baseConfig: errorTrackingWidgetConfigSchema.parse({
                dateRange: { date_from: '-30d' },
                status: 'resolved',
            }),
        })

        expect(result.success).toBe(true)
        if (result.success) {
            expect(result.config.limit).toBe(10)
            expect(result.config.dateRange).toEqual({ date_from: '-30d' })
            expect(result.config.status).toBe('resolved')
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
})

describe('parseErrorTrackingWidgetConfigApiError', () => {
    it('maps invalid config to zod field errors', () => {
        const error = new ApiError('limit must be an integer between 1 and 25.', 400, undefined, {
            config: 'limit must be an integer between 1 and 25.',
        })

        expect(
            parseErrorTrackingWidgetConfigApiError(error, {
                limit: 30,
                orderBy: 'occurrences',
                orderDirection: 'DESC',
                status: 'active',
                dateRange: { date_from: '-7d' },
            })
        ).toEqual({
            limit: 'Too big: expected number to be <=25',
        })
    })
})

describe('patchErrorTrackingWidgetFilterFields', () => {
    it('updates status while preserving sort fields', () => {
        const base = errorTrackingWidgetConfigSchema.parse({
            limit: 5,
            orderBy: 'users',
            status: 'active',
            dateRange: { date_from: '-7d' },
        })
        const next = patchErrorTrackingWidgetFilterFields(base, { status: 'resolved' })
        expect(next.status).toBe('resolved')
        expect(next.limit).toBe(5)
        expect(next.orderBy).toBe('users')
    })

    it('persists widgetFilters patch on tile config', () => {
        const base = errorTrackingWidgetConfigSchema.parse({
            limit: 5,
            orderBy: 'occurrences',
            status: 'active',
            dateRange: { date_from: '-7d' },
        })
        const next = patchErrorTrackingWidgetFilterFields(base, {
            widgetFilters: {
                'qf-1': {
                    filterId: 'qf-1',
                    propertyName: '$environment',
                    optionId: 'opt-1',
                    value: 'production',
                    operator: PropertyOperator.Exact,
                },
            },
        })
        expect(next.widgetFilters?.['qf-1']?.propertyName).toBe('$environment')
    })
})
