import { otherRegionLoginUrl, otherRegionOf } from 'scenes/authentication/shared/OtherRegionHint'

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
})
