import { WebAnalyticsPropertyFilter } from '~/queries/schema/schema-general'
import { PropertyFilterBaseValue, PropertyFilterType, PropertyOperator } from '~/types'

import { appendFilterParams } from './liveWebAnalyticsMetricsLogic'

const filter = (key: string, value: string | string[]): WebAnalyticsPropertyFilter => ({
    type: PropertyFilterType.Event,
    key,
    value,
    operator: PropertyOperator.Exact,
})

describe('appendFilterParams', () => {
    it.each([
        { label: 'empty list appends nothing', filters: [] as WebAnalyticsPropertyFilter[], expected: [] },
        {
            label: 'scalar filter appends a single property entry',
            filters: [filter('$host', 'example.com')],
            expected: ['$host=example.com'],
        },
        {
            label: 'array value appends one entry per element',
            filters: [filter('$device_type', ['Mobile', 'Tablet'])],
            expected: ['$device_type=Mobile', '$device_type=Tablet'],
        },
        {
            label: 'mixed list appends one entry per filter',
            filters: [
                filter('$host', 'example.com'),
                filter('$geoip_country_code', 'US'),
                filter('$device_type', ['Mobile', 'Tablet']),
                filter('$referring_domain', 'twitter.com'),
            ],
            expected: [
                '$host=example.com',
                '$geoip_country_code=US',
                '$device_type=Mobile',
                '$device_type=Tablet',
                '$referring_domain=twitter.com',
            ],
        },
        {
            label: 'skips filters that use a non-Exact operator',
            filters: [
                { type: PropertyFilterType.Event, key: '$host', value: 'foo', operator: PropertyOperator.IsNot },
            ] as WebAnalyticsPropertyFilter[],
            expected: [],
        },
        {
            label: 'skips filters that are not event properties',
            filters: [
                {
                    type: PropertyFilterType.Person,
                    key: 'email',
                    value: 'test@example.com',
                    operator: PropertyOperator.Exact,
                },
            ] as WebAnalyticsPropertyFilter[],
            expected: [],
        },
        {
            label: 'skips null entries within an array value',
            filters: [
                {
                    type: PropertyFilterType.Event,
                    key: '$host',
                    value: [null, 'bar'] as unknown as PropertyFilterBaseValue[],
                    operator: PropertyOperator.Exact,
                } as WebAnalyticsPropertyFilter,
            ],
            expected: ['$host=bar'],
        },
        {
            label: 'preserves existing query params on the URL',
            url: 'https://example.com/events?columns=$pathname&geo=true',
            filters: [filter('$host', 'example.com')],
            expected: ['$host=example.com'],
            preservedParams: { columns: '$pathname', geo: 'true' },
        },
    ])('$label', ({ filters, expected, url, preservedParams }) => {
        const u = new URL(url ?? 'https://example.com/events')
        appendFilterParams(u, filters)
        expect(u.searchParams.getAll('property')).toEqual(expected)
        for (const [key, value] of Object.entries(preservedParams ?? {})) {
            expect(u.searchParams.get(key)).toEqual(value)
        }
    })
})
