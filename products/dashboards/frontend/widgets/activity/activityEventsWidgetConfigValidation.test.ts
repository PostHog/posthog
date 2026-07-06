import { ApiError } from 'lib/api-error'

import { activityEventsWidgetConfigSchema } from '../../generated/widget-configs.zod'
import {
    ACTIVITY_EVENTS_WIDGET_FORM_FIELD_NAMES,
    parseActivityEventsWidgetConfigApiError,
    patchActivityEventsWidgetFilterFields,
    validateActivityEventsWidgetConfigInput,
} from './activityEventsWidgetConfigValidation'

describe('activityEventsWidgetConfigValidation', () => {
    it('form picked fields exist on the generated config schema', () => {
        const shape = activityEventsWidgetConfigSchema.shape
        for (const field of ACTIVITY_EVENTS_WIDGET_FORM_FIELD_NAMES) {
            expect(shape).toHaveProperty(field)
        }
    })

    describe('validateActivityEventsWidgetConfigInput', () => {
        it('rejects limit above 50 with inline-friendly message', () => {
            const result = validateActivityEventsWidgetConfigInput({
                limit: 60,
                filterTestAccounts: true,
                baseConfig: activityEventsWidgetConfigSchema.parse({}),
            })

            expect(result.success).toBe(false)
            if (!result.success) {
                expect(result.fieldErrors.limit).toBe('Too big: expected number to be <=50')
            }
        })

        it('accepts valid config and preserves the date range from base config', () => {
            const result = validateActivityEventsWidgetConfigInput({
                limit: 10,
                filterTestAccounts: true,
                baseConfig: activityEventsWidgetConfigSchema.parse({
                    dateRange: { date_from: '-7d' },
                }),
            })

            expect(result.success).toBe(true)
            if (result.success) {
                expect(result.config.limit).toBe(10)
                expect(result.config.dateRange).toEqual({ date_from: '-7d' })
                expect(result.config.filterTestAccounts).toBe(true)
            }
        })
    })

    describe('patchActivityEventsWidgetFilterFields', () => {
        it('updates the date range without clearing other config fields', () => {
            const config = activityEventsWidgetConfigSchema.parse({
                limit: 15,
                dateRange: { date_from: '-24h' },
            })

            const next = patchActivityEventsWidgetFilterFields(config, { dateFrom: '-7d' })

            expect(next.dateRange).toEqual({ date_from: '-7d' })
            expect(next.limit).toBe(15)
        })

        it('sets and clears the event name without touching the date range', () => {
            const config = activityEventsWidgetConfigSchema.parse({ limit: 15, dateRange: { date_from: '-7d' } })

            const withEvent = patchActivityEventsWidgetFilterFields(config, { eventName: '$pageview' })
            expect(withEvent.eventName).toBe('$pageview')
            expect(withEvent.dateRange).toEqual({ date_from: '-7d' })

            const cleared = patchActivityEventsWidgetFilterFields(withEvent, { eventName: null })
            expect(cleared.eventName).toBeNull()
        })
    })

    describe('parseActivityEventsWidgetConfigApiError', () => {
        it('maps invalid config to zod field errors', () => {
            const error = new ApiError('limit must be an integer between 1 and 50.', 400, undefined, {
                config: 'limit must be an integer between 1 and 50.',
            })

            expect(
                parseActivityEventsWidgetConfigApiError(error, {
                    limit: 60,
                    dateRange: { date_from: '-24h' },
                })
            ).toEqual({
                limit: 'Too big: expected number to be <=50',
            })
        })
    })
})
