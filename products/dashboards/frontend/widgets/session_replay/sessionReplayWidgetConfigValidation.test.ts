import { ApiError } from 'lib/api-error'

import { sessionReplayWidgetConfigSchema } from '../../generated/widget-configs.zod'
import {
    SESSION_REPLAY_WIDGET_FORM_FIELD_NAMES,
    parseSessionReplayWidgetConfigApiError,
    patchSessionReplayWidgetFilterFields,
    validateSessionReplayWidgetConfigInput,
} from './sessionReplayWidgetConfigValidation'

describe('sessionReplayWidgetConfigValidation', () => {
    it('form picked fields exist on the generated config schema', () => {
        const shape = sessionReplayWidgetConfigSchema.shape
        for (const field of SESSION_REPLAY_WIDGET_FORM_FIELD_NAMES) {
            expect(shape).toHaveProperty(field)
        }
    })
})

describe('validateSessionReplayWidgetConfigInput', () => {
    it('rejects limit above 25 with inline-friendly message', () => {
        const result = validateSessionReplayWidgetConfigInput({
            limit: 30,
            orderBy: 'start_time',
            orderDirection: 'DESC',
            filterTestAccounts: true,
            baseConfig: sessionReplayWidgetConfigSchema.parse({}),
        })

        expect(result.success).toBe(false)
        if (!result.success) {
            expect(result.fieldErrors.limit).toBe('Too big: expected number to be <=25')
        }
    })

    it('rejects invalid order direction', () => {
        const result = validateSessionReplayWidgetConfigInput({
            limit: 10,
            orderBy: 'start_time',
            orderDirection: 'SIDEWAYS',
            filterTestAccounts: true,
            baseConfig: sessionReplayWidgetConfigSchema.parse({}),
        })

        expect(result.success).toBe(false)
    })

    it('accepts valid config and preserves tile filter fields from base config', () => {
        const result = validateSessionReplayWidgetConfigInput({
            limit: 10,
            orderBy: 'start_time',
            orderDirection: 'ASC',
            filterTestAccounts: true,
            baseConfig: sessionReplayWidgetConfigSchema.parse({
                dateRange: { date_from: '-30d' },
                widgetFilters: {
                    'qf-1': {
                        filterId: 'qf-1',
                        propertyName: '$browser',
                        optionId: 'opt-1',
                        operator: 'exact',
                        value: 'Chrome',
                    },
                },
            }),
        })

        expect(result.success).toBe(true)
        if (result.success) {
            expect(result.config.limit).toBe(10)
            expect(result.config.orderDirection).toBe('ASC')
            expect(result.config.dateRange).toEqual({ date_from: '-30d' })
            expect(result.config.filterTestAccounts).toBe(true)
            expect(result.config.widgetFilters?.['qf-1']).toMatchObject({
                propertyName: '$browser',
                value: 'Chrome',
            })
        }
    })
})

describe('patchSessionReplayWidgetFilterFields', () => {
    it('updates date range without clearing widget filters', () => {
        const config = sessionReplayWidgetConfigSchema.parse({
            dateRange: { date_from: '-7d' },
            widgetFilters: {
                'qf-1': {
                    filterId: 'qf-1',
                    propertyName: '$browser',
                    optionId: 'opt-1',
                    operator: 'exact',
                    value: 'Chrome',
                },
            },
        })

        const next = patchSessionReplayWidgetFilterFields(config, { dateFrom: '-30d' })

        expect(next.dateRange).toEqual({ date_from: '-30d' })
        expect(next.widgetFilters?.['qf-1']).toMatchObject({ value: 'Chrome' })
    })

    it('sets and clears the saved filter without dropping other tile filters', () => {
        const config = sessionReplayWidgetConfigSchema.parse({ dateRange: { date_from: '-7d' } })

        const withSavedFilter = patchSessionReplayWidgetFilterFields(config, { savedFilterId: 'abc123' })
        expect(withSavedFilter.savedFilterId).toBe('abc123')

        const dateChanged = patchSessionReplayWidgetFilterFields(withSavedFilter, { dateFrom: '-30d' })
        expect(dateChanged.savedFilterId).toBe('abc123')

        const cleared = patchSessionReplayWidgetFilterFields(dateChanged, { savedFilterId: null })
        expect(cleared.savedFilterId).toBeNull()
        expect(cleared.dateRange).toEqual({ date_from: '-30d' })
    })

    it('sets a collection and saved filter independently so they can be combined', () => {
        const config = sessionReplayWidgetConfigSchema.parse({})

        // A collection (scope) and a saved filter (refinement) coexist — neither clears the other.
        const withCollection = patchSessionReplayWidgetFilterFields(config, { collectionId: 'col123' })
        expect(withCollection.collectionId).toBe('col123')
        expect(withCollection.savedFilterId).toBeNull()

        const withBoth = patchSessionReplayWidgetFilterFields(withCollection, { savedFilterId: 'abc123' })
        expect(withBoth.collectionId).toBe('col123')
        expect(withBoth.savedFilterId).toBe('abc123')

        // Clearing one leaves the other untouched.
        const collectionCleared = patchSessionReplayWidgetFilterFields(withBoth, { collectionId: null })
        expect(collectionCleared.collectionId).toBeNull()
        expect(collectionCleared.savedFilterId).toBe('abc123')
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
            limit: 'Too big: expected number to be <=25',
        })
    })
})
