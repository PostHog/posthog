import { AnyPropertyFilter, PropertyFilterBaseValue, PropertyFilterType, PropertyOperator } from '~/types'

import { appendFilterParams } from './liveWebAnalyticsMetricsLogic'

const filter = (
    key: string,
    value: string | string[],
    operator: PropertyOperator = PropertyOperator.Exact
): AnyPropertyFilter => ({ type: PropertyFilterType.Event, key, value, operator }) as AnyPropertyFilter

describe('appendFilterParams', () => {
    it.each([
        { label: 'empty list appends nothing', filters: [] as AnyPropertyFilter[], expected: null },
        {
            label: 'scalar filter serializes value as an array',
            filters: [filter('$host', 'example.com')],
            expected: [{ key: '$host', operator: 'exact', value: ['example.com'] }],
        },
        {
            label: 'array value stays a single entry matched as IN',
            filters: [filter('$device_type', ['Mobile', 'Tablet'])],
            expected: [{ key: '$device_type', operator: 'exact', value: ['Mobile', 'Tablet'] }],
        },
        {
            label: 'forwards the operator for non-exact event filters',
            filters: [
                filter('$host', 'localhost', PropertyOperator.IContains),
                filter('$current_url', '/admin', PropertyOperator.NotIContains),
                filter('$referring_domain', '^https://', PropertyOperator.Regex),
                filter('$device_type', 'Desktop', PropertyOperator.IsNot),
            ],
            expected: [
                { key: '$host', operator: 'icontains', value: ['localhost'] },
                { key: '$current_url', operator: 'not_icontains', value: ['/admin'] },
                { key: '$referring_domain', operator: 'regex', value: ['^https://'] },
                { key: '$device_type', operator: 'is_not', value: ['Desktop'] },
            ],
        },
        {
            label: 'set operators carry no values',
            filters: [filter('$browser', '', PropertyOperator.IsSet)],
            expected: [{ key: '$browser', operator: 'is_set', value: [] }],
        },
        {
            label: 'skips operators the livestream cannot compile',
            filters: [filter('$host', '2024-01-01', PropertyOperator.IsDateAfter)],
            expected: null,
        },
        {
            label: 'skips person filters, which the raw event payload cannot satisfy',
            filters: [
                {
                    type: PropertyFilterType.Person,
                    key: 'email',
                    value: 'test@example.com',
                    operator: PropertyOperator.Exact,
                },
            ] as AnyPropertyFilter[],
            expected: null,
        },
        {
            label: 'skips cohort filters, which the raw event payload cannot satisfy',
            filters: [
                { type: PropertyFilterType.Cohort, key: 'id', value: 426532, operator: PropertyOperator.NotIn },
            ] as AnyPropertyFilter[],
            expected: null,
        },
        {
            label: 'drops null entries within an array value',
            filters: [
                {
                    type: PropertyFilterType.Event,
                    key: '$host',
                    value: [null, 'bar'] as unknown as PropertyFilterBaseValue[],
                    operator: PropertyOperator.Exact,
                } as AnyPropertyFilter,
            ],
            expected: [{ key: '$host', operator: 'exact', value: ['bar'] }],
        },
        {
            label: 'drops a filter whose values are all null',
            filters: [
                {
                    type: PropertyFilterType.Event,
                    key: '$host',
                    value: [null] as unknown as PropertyFilterBaseValue[],
                    operator: PropertyOperator.Exact,
                } as AnyPropertyFilter,
            ],
            expected: null,
        },
        {
            label: 'preserves existing query params on the URL',
            url: 'https://example.com/events?columns=$pathname&geo=true',
            filters: [filter('$host', 'example.com')],
            expected: [{ key: '$host', operator: 'exact', value: ['example.com'] }],
            preservedParams: { columns: '$pathname', geo: 'true' },
        },
    ])('$label', ({ filters, expected, url, preservedParams }) => {
        const u = new URL(url ?? 'https://example.com/events')
        appendFilterParams(u, filters)
        const raw = u.searchParams.get('properties')
        expect(raw === null ? null : JSON.parse(raw)).toEqual(expected)
        for (const [key, value] of Object.entries(preservedParams ?? {})) {
            expect(u.searchParams.get(key)).toEqual(value)
        }
    })
})
