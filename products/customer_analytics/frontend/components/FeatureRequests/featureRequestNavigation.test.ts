import { urls } from 'scenes/urls'

import {
    getFeatureRequestBackLabel,
    getFeatureRequestBackUrl,
    getFeatureRequestDetailUrl,
} from './featureRequestNavigation'

describe('feature request navigation', () => {
    it('links an account request back to its feature requests tab', () => {
        const accountOrigin = urls.customerAnalyticsAccount('account-1', 'feature_requests')
        const detailUrl = new URL(
            getFeatureRequestDetailUrl({
                requestId: 'request-1',
                origin: accountOrigin,
                searchParams: { evidence_account: 'account-1' },
            }),
            'https://posthog.test'
        )

        expect(detailUrl.pathname).toBe(urls.customerAnalyticsFeatureRequests('request-1'))
        expect(detailUrl.searchParams.get('origin')).toBe(accountOrigin)
        expect(detailUrl.searchParams.get('evidence_account')).toBe('account-1')
    })

    it('returns to the supplied internal origin', () => {
        const origin = `${urls.customerAnalyticsAccount('account-1', 'feature_requests')}?tab=details`

        expect(getFeatureRequestBackUrl(origin, { status: 'planned' })).toBe(origin)
        expect(getFeatureRequestBackLabel(origin)).toBeNull()
    })

    it.each([undefined, 'https://example.com/accounts', '//example.com/accounts', '/\\example.com/accounts'])(
        'returns direct visits with origin %s to the filtered request list',
        (origin) => {
            expect(getFeatureRequestBackUrl(origin, { status: 'planned' })).toBe(
                `${urls.customerAnalyticsFeatureRequests()}?status=planned`
            )
            expect(getFeatureRequestBackLabel(origin)).toBe('Feature requests')
        }
    )
})
