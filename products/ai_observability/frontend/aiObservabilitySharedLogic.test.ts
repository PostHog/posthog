import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { buildApplyUrlStatePayload, stripStaleSearchParams } from './aiObservabilitySharedLogic'

describe('stripStaleSearchParams', () => {
    it('returns null when every param is preserved', () => {
        expect(
            stripStaleSearchParams({
                date_from: '-7d',
                filter_test_accounts: 'true',
                review_search: 'hallucination',
                human_reviews_tab: 'reviews',
            })
        ).toBeNull()
    })

    it('keeps Reviews-tab params while stripping trace-view stale params', () => {
        expect(
            stripStaleSearchParams({
                review_search: 'hallucination',
                review_definition_id: 'def-123',
                review_order_by: 'created_at',
                review_page: 2,
                human_reviews_tab: 'reviews',
                // stale params carried over from the trace view
                event: 'evt-1',
                timestamp: '2026-04-01',
                msg: 'whatever',
            })
        ).toEqual({
            review_search: 'hallucination',
            review_definition_id: 'def-123',
            review_order_by: 'created_at',
            review_page: 2,
            human_reviews_tab: 'reviews',
        })
    })

    it('keeps shared filter params alongside stripping stale ones', () => {
        expect(
            stripStaleSearchParams({
                date_from: '-30d',
                filters: [{ key: '$ai_model' }],
                back_to: 'generations',
            })
        ).toEqual({
            date_from: '-30d',
            filters: [{ key: '$ai_model' }],
        })
    })
})

describe('buildApplyUrlStatePayload', () => {
    const currentDateFilter = { dateFrom: '-1h', dateTo: null as string | null }
    const currentPropertyFilters: AnyPropertyFilter[] = []

    it.each([
        { desc: 'dateFrom differs', dateFrom: '-7d', dateTo: null as string | null, expected: true },
        { desc: 'dateTo differs', dateFrom: '-1h', dateTo: '2026-04-01', expected: true },
        { desc: 'both match current', dateFrom: '-1h', dateTo: null as string | null, expected: false },
    ])('flags datesChanged=$expected when $desc', ({ dateFrom, dateTo, expected }) => {
        const payload = buildApplyUrlStatePayload({
            dateFrom,
            dateTo,
            shouldFilterTestAccounts: false,
            propertyFilters: [],
            currentDateFilter,
            currentPropertyFilters,
        })
        expect(payload.datesChanged).toBe(expected)
    })

    const modelFilter: AnyPropertyFilter = {
        type: PropertyFilterType.Event,
        key: '$ai_model',
        operator: PropertyOperator.Exact,
        value: ['gpt-4o'],
    }
    it.each([
        {
            desc: 'contents equal — returns current reference',
            current: [modelFilter],
            next: [{ ...modelFilter }],
            expectCurrentRef: true,
        },
        {
            desc: 'contents differ — returns next reference',
            current: [] as AnyPropertyFilter[],
            next: [modelFilter],
            expectCurrentRef: false,
        },
    ])('propertyFilters: $desc', ({ current, next, expectCurrentRef }) => {
        const payload = buildApplyUrlStatePayload({
            dateFrom: '-1h',
            dateTo: null,
            shouldFilterTestAccounts: false,
            propertyFilters: next,
            currentDateFilter,
            currentPropertyFilters: current,
        })
        expect(payload.propertyFilters).toBe(expectCurrentRef ? current : next)
    })

    it('passes through shouldFilterTestAccounts and date values unchanged', () => {
        const payload = buildApplyUrlStatePayload({
            dateFrom: '-30d',
            dateTo: '-1d',
            shouldFilterTestAccounts: true,
            propertyFilters: [],
            currentDateFilter,
            currentPropertyFilters,
        })
        expect(payload.dateFrom).toBe('-30d')
        expect(payload.dateTo).toBe('-1d')
        expect(payload.shouldFilterTestAccounts).toBe(true)
    })
})
