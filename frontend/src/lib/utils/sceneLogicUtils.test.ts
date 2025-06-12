import { withForwardedSearchParams } from './sceneLogicUtils'

describe('sceneLogicUtils', () => {
    describe('withForwardedSearchParams', () => {
        it('returns original URL when no params to forward', () => {
            const redirectUrl = '/dashboard'
            const currentSearchParams = { invite_modal: 'true', other: 'value' }
            const forwardedQueryParams: string[] = []

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard')
        })

        it('returns original URL when forwarded params do not exist in current search params', () => {
            const redirectUrl = '/dashboard'
            const currentSearchParams = { other: 'value' }
            const forwardedQueryParams = ['invite_modal', 'next']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard')
        })

        it('returns original URL when forwarded param already exists in redirect URL', () => {
            const redirectUrl = '/dashboard?invite_modal=existing'
            const currentSearchParams = { invite_modal: 'true' }
            const forwardedQueryParams = ['invite_modal']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard?invite_modal=existing')
        })

        it('forwards multiple params when they exist in current search params', () => {
            const redirectUrl = '/dashboard'
            const currentSearchParams = { invite_modal: 'true', next: '/insights', other: 'ignored' }
            const forwardedQueryParams = ['invite_modal', 'next']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard?invite_modal=true&next=%2Finsights')
        })

        it('preserves existing query params in redirect URL while adding forwarded ones', () => {
            const redirectUrl = '/dashboard?existing=value'
            const currentSearchParams = { invite_modal: 'true' }
            const forwardedQueryParams = ['invite_modal']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard?existing=value&invite_modal=true')
        })

        it('preserves hash in redirect URL', () => {
            const redirectUrl = '/dashboard?existing=value#section?nested=param'
            const currentSearchParams = { invite_modal: 'true' }
            const forwardedQueryParams = ['invite_modal']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard?existing=value&invite_modal=true#section?nested=param')
        })

        it('handles URL encoding correctly', () => {
            const redirectUrl = '/dashboard'
            const currentSearchParams = { next: '/insights?filter=test&other=value' }
            const forwardedQueryParams = ['next']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard?next=%2Finsights%3Ffilter%3Dtest%26other%3Dvalue')
        })

        it('handles empty string values', () => {
            const redirectUrl = '/dashboard'
            const currentSearchParams = { invite_modal: '' }
            const forwardedQueryParams = ['invite_modal']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard?invite_modal=')
        })

        it('forwards param with falsy values', () => {
            const redirectUrl = '/dashboard'
            const currentSearchParams = {
                invite_modal: null,
                next: undefined,
                other: false,
                empty: '',
            }
            const forwardedQueryParams = ['invite_modal', 'next', 'other', 'empty']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard?invite_modal=null&other=false&empty=')
        })

        it('never overwrites existing params in redirect URL', () => {
            const redirectUrl = '/dashboard?invite_modal=existing&other=preserved'
            const currentSearchParams = {
                invite_modal: 'new-value',
                next: '/destination',
                other: 'different',
            }
            const forwardedQueryParams = ['invite_modal', 'next', 'other']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            // Only 'next' should be added since 'invite_modal' and 'other' already exist
            expect(result).toBe('/dashboard?invite_modal=existing&other=preserved&next=%2Fdestination')
        })

        it('preserves existing params even with empty values in redirect URL', () => {
            const redirectUrl = '/dashboard?invite_modal='
            const currentSearchParams = { invite_modal: 'true' }
            const forwardedQueryParams = ['invite_modal']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard?invite_modal=')
        })
    })
})
