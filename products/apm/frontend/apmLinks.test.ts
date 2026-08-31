import { combineUrl } from 'kea-router'

import { parseTagsFilter } from 'lib/utils/url'

import { apmFacetUrl } from './apmLinks'
import { DEFAULT_APM_TAB } from './apmSceneLogic'

describe('apmFacetUrl', () => {
    it('carries nothing but the path when nothing was chosen', () => {
        // Defaults in a shared link are noise, and they also pin the recipient to a window the
        // sender never picked.
        expect(apmFacetUrl(DEFAULT_APM_TAB)).toEqual('/apm')
    })

    it.each([
        ['traces', 'traces'],
        ['metrics', 'metrics'],
    ] as const)('names the %s facet', (tab, expected) => {
        expect(combineUrl(apmFacetUrl(tab)).searchParams.tab).toEqual(expected)
    })

    it('scopes to a service in the form the scene reads back', () => {
        // The regression this catches is format drift: if the writer and `apmSceneLogic`'s
        // reader disagree, the link silently lands unscoped instead of failing.
        const url = apmFacetUrl('metrics', { serviceName: 'checkout-api' })

        expect(parseTagsFilter(combineUrl(url).searchParams.serviceNames)).toEqual(['checkout-api'])
    })

    it('round-trips a date range', () => {
        const dateRange = { date_from: '-24h', date_to: null }

        const url = apmFacetUrl('logs', { dateRange })

        expect(JSON.parse(combineUrl(url).searchParams.dateRange)).toEqual(dateRange)
    })
})
