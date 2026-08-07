import { ApiError } from 'lib/api-error'

import { FilterType } from '~/types'

import {
    UsageMetricFormData,
    actionFilterValueToSavedFilters,
    dataWarehouseFiltersError,
    usageMetricErrorMessage,
} from './usageMetricsConfigLogic'

describe('usageMetricsConfigLogic helpers', () => {
    describe('dataWarehouseFiltersError', () => {
        it('returns undefined for events metrics regardless of missing DW fields', () => {
            expect(dataWarehouseFiltersError({ events: [{ id: '$pageview' }] } as FilterType)).toBeUndefined()
        })

        it.each<[string, UsageMetricFormData['filters'], string | undefined]>([
            [
                'missing table_name',
                { source: 'data_warehouse', table_name: null, timestamp_field: 'ts', key_field: 'k' },
                'Select a data warehouse table',
            ],
            [
                'missing timestamp_field',
                { source: 'data_warehouse', table_name: 'stripe', timestamp_field: null, key_field: 'k' },
                'Select the timestamp column for this table',
            ],
            [
                'missing key_field',
                { source: 'data_warehouse', table_name: 'stripe', timestamp_field: 'ts', key_field: null },
                'Select the group key column for this table',
            ],
            [
                'all present',
                { source: 'data_warehouse', table_name: 'stripe', timestamp_field: 'ts', key_field: 'k' },
                undefined,
            ],
        ])('%s', (_name, filters, expected) => {
            expect(dataWarehouseFiltersError(filters)).toEqual(expected)
        })

        it('flags the fields dropped when switching an events metric to a warehouse table', () => {
            // The ActionFilter hands back a DW entry with only the table name; the popover fields were never collected.
            const switched = actionFilterValueToSavedFilters(
                { data_warehouse: [{ table_name: 'stripe', name: 'stripe' }] } as FilterType,
                'events'
            )
            expect(dataWarehouseFiltersError(switched)).toEqual('Select the timestamp column for this table')
        })
    })

    describe('usageMetricErrorMessage', () => {
        it('prefers the DRF detail off an ApiError', () => {
            const error = new ApiError('save failed', 400, undefined, {
                detail: 'Data warehouse metrics require table_name, timestamp_field, key_field.',
            })
            expect(usageMetricErrorMessage(error, 'fallback')).toEqual(
                'Data warehouse metrics require table_name, timestamp_field, key_field.'
            )
        })

        it('falls back to the loader message, then a default, when no detail is present', () => {
            expect(usageMetricErrorMessage(new ApiError(undefined, 500), 'loader message')).toEqual('loader message')
            expect(usageMetricErrorMessage(null)).toEqual('Could not save usage metric. Please try again.')
        })
    })
})
