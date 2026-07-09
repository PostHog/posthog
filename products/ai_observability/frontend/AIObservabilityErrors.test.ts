import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { type AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { buildErrorTracesUrl } from './AIObservabilityErrors'

describe('AIObservabilityErrors', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('links to traces with the raw normalized error value', () => {
        const existingFilter: AnyPropertyFilter = {
            type: PropertyFilterType.Event,
            key: '$ai_model',
            operator: PropertyOperator.Exact,
            value: 'gpt-4o',
        }
        const errorString = 'TypeError: Cannot read "message" at C:\\app\\index.ts'

        const url = buildErrorTracesUrl(errorString, { date_from: '-24h' }, [existingFilter])
        router.actions.push(url)

        expect(router.values.location.pathname.endsWith(urls.aiObservabilityTraces())).toBe(true)
        expect(router.values.searchParams).toMatchObject({ date_from: '-24h' })
        expect(router.values.searchParams.filters).toEqual([
            existingFilter,
            {
                type: PropertyFilterType.Event,
                key: '$ai_is_error',
                operator: PropertyOperator.Exact,
                value: 'true',
            },
            {
                type: PropertyFilterType.Event,
                key: '$ai_error_normalized',
                operator: PropertyOperator.Exact,
                value: errorString,
            },
        ])
    })
})
