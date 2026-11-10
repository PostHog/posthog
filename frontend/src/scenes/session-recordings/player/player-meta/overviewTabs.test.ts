import { OverviewItem } from 'scenes/session-recordings/components/OverviewGrid'

import { PropertyFilterType } from '~/types'

import { OverviewTab, groupOverviewItemsByTab, overviewTabForProperty } from './overviewTabs'

const item = (property: string, propertyFilterType: PropertyFilterType): OverviewItem => ({
    type: 'property',
    property,
    label: property,
    value: 'x',
    propertyFilterType,
})

describe('overviewTabs', () => {
    it.each<[string, OverviewItem, OverviewTab]>([
        ['hardcoded text item', { type: 'text', label: 'Duration', value: '1m' }, 'session'],
        ['session url property', item('$entry_current_url', PropertyFilterType.Session), 'session'],
        ['person property', item('email', PropertyFilterType.Person), 'person'],
        ['geoip session property', item('$geoip_country_code', PropertyFilterType.Session), 'device'],
        ['browser event property', item('$browser', PropertyFilterType.Event), 'device'],
        ['geoip person property', item('$geoip_city_name', PropertyFilterType.Person), 'device'],
    ])('routes %s', (_, overviewItem, expected) => {
        const grouped = groupOverviewItemsByTab([overviewItem])
        expect(grouped[expected]).toEqual([overviewItem])
    })

    it.each<[string, PropertyFilterType | undefined, OverviewTab]>([
        ['$entry_pathname', PropertyFilterType.Session, 'session'],
        ['$os_name', undefined, 'device'],
        ['plan', PropertyFilterType.Person, 'person'],
    ])('routes the key %s', (property, propertyFilterType, expected) => {
        expect(overviewTabForProperty(property, propertyFilterType)).toBe(expected)
    })
})
