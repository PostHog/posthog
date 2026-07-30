import { getSourceOAuthRedirectUrl } from '../IntegrationChoice'

describe('getSourceOAuthRedirectUrl', () => {
    it('keeps the return context passed by product-embedded entry points', () => {
        const url = getSourceOAuthRedirectUrl(
            '/project/1/data-warehouse/new-source',
            '?kind=MetaAds&returnUrl=%2Fproject%2F1%2Fweb%2Fmarketing&returnLabel=Marketing+analytics',
            'metaads'
        )

        const params = new URLSearchParams(url.split('?')[1])
        expect(url.split('?')[0]).toEqual('/data-warehouse/new-source')
        expect(params.get('kind')).toEqual('metaads')
        expect(params.get('returnUrl')).toEqual('/project/1/web/marketing')
        expect(params.get('returnLabel')).toEqual('Marketing analytics')
    })

    it('returns to the onboarding page rather than the standalone wizard', () => {
        const url = getSourceOAuthRedirectUrl('/project/1/onboarding/data_warehouse', '?step=sources', 'stripe')

        expect(url).toEqual('/project/1/onboarding/data_warehouse?step=sources&kind=stripe')
    })
})
