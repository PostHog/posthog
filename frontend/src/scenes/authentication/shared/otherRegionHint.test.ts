import {
    otherRegionLoginUrl,
    otherRegionOf,
    otherRegionSamePathUrl,
} from 'scenes/authentication/shared/OtherRegionHint'

import { Region } from '~/types'

describe('OtherRegionHint', () => {
    test.each([
        ['US points to EU', Region.US, Region.EU],
        ['EU points to US', Region.EU, Region.US],
    ])('otherRegionOf: %s', (_name, region, expected) => {
        expect(otherRegionOf(region)).toEqual(expected)
    })

    test.each([
        ['US with no query lands on eu login', Region.US, '', 'https://eu.posthog.com/login'],
        ['EU with no query lands on us login', Region.EU, '', 'https://us.posthog.com/login'],
        ['preserves the next query param', Region.US, '?next=/home', 'https://eu.posthog.com/login?next=/home'],
    ])('otherRegionLoginUrl: %s', (_name, region, search, expected) => {
        expect(otherRegionLoginUrl(region, search)).toEqual(expected)
    })

    test.each([
        [
            'keeps the project path when moving from US to EU',
            Region.US,
            { pathname: '/project/1234/dashboard/5', search: '', hash: '' },
            'https://eu.posthog.com/project/1234/dashboard/5',
        ],
        [
            'keeps the project path when moving from EU to US',
            Region.EU,
            { pathname: '/project/1234/dashboard/5', search: '', hash: '' },
            'https://us.posthog.com/project/1234/dashboard/5',
        ],
        [
            'keeps the query string and hash',
            Region.US,
            { pathname: '/project/1234/replay', search: '?filters=1', hash: '#panel=support' },
            'https://eu.posthog.com/project/1234/replay?filters=1#panel=support',
        ],
    ])('otherRegionSamePathUrl: %s', (_name, region, location, expected) => {
        expect(otherRegionSamePathUrl(region, location)).toEqual(expected)
    })
})
