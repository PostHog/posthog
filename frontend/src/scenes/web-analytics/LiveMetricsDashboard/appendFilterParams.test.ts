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
    it('appends nothing when the filter list is empty', () => {
        const url = new URL('https://example.com/events')
        appendFilterParams(url, [])
        expect(url.searchParams.getAll('property')).toEqual([])
    })

    it('appends a single property=key=value entry for a scalar filter', () => {
        const url = new URL('https://example.com/events')
        appendFilterParams(url, [filter('$host', 'example.com')])
        expect(url.searchParams.getAll('property')).toEqual(['$host=example.com'])
    })

    it('appends repeated property entries for array values (Mobile -> [Mobile, Tablet])', () => {
        const url = new URL('https://example.com/events')
        appendFilterParams(url, [filter('$device_type', ['Mobile', 'Tablet'])])
        expect(url.searchParams.getAll('property')).toEqual(['$device_type=Mobile', '$device_type=Tablet'])
    })

    it('appends one entry per filter for a mixed list', () => {
        const url = new URL('https://example.com/events')
        appendFilterParams(url, [
            filter('$host', 'example.com'),
            filter('$geoip_country_code', 'US'),
            filter('$device_type', ['Mobile', 'Tablet']),
            filter('$referring_domain', 'twitter.com'),
        ])
        expect(url.searchParams.getAll('property')).toEqual([
            '$host=example.com',
            '$geoip_country_code=US',
            '$device_type=Mobile',
            '$device_type=Tablet',
            '$referring_domain=twitter.com',
        ])
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
