import { WebAnalyticsPropertyFilter } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

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
    ])('$label', ({ filters, expected }) => {
        const url = new URL('https://example.com/events')
        appendFilterParams(url, filters)
        expect(url.searchParams.getAll('property')).toEqual(expected)
    })

    it('skips filters that use a non-Exact operator', () => {
        const url = new URL('https://example.com/events')
        appendFilterParams(url, [
            { type: PropertyFilterType.Event, key: '$host', value: 'foo', operator: PropertyOperator.IsNot },
        ])
        expect(url.searchParams.getAll('property')).toEqual([])
    })

    it('skips null entries within an array value', () => {
        const url = new URL('https://example.com/events')
        appendFilterParams(url, [
            { type: PropertyFilterType.Event, key: '$host', value: [null, 'bar'], operator: PropertyOperator.Exact },
        ])
        expect(url.searchParams.getAll('property')).toEqual(['$host=bar'])
    })

    it('preserves existing query params on the URL', () => {
        const url = new URL('https://example.com/events?columns=$pathname&geo=true')
        appendFilterParams(url, [filter('$host', 'example.com')])
        expect(url.searchParams.get('columns')).toEqual('$pathname')
        expect(url.searchParams.get('geo')).toEqual('true')
        expect(url.searchParams.getAll('property')).toEqual(['$host=example.com'])
    })
})
