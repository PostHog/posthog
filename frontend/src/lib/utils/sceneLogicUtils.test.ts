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

        it('forwards single param when it exists in current search params and not in redirect URL', () => {
            const redirectUrl = '/dashboard'
            const currentSearchParams = { invite_modal: 'true' }
            const forwardedQueryParams = ['invite_modal']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard?invite_modal=true')
        })

        it('forwards multiple params when they exist in current search params', () => {
            const redirectUrl = '/dashboard'
            const currentSearchParams = { invite_modal: 'true', next: '/insights', other: 'ignored' }
            const forwardedQueryParams = ['invite_modal', 'next']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard?invite_modal=true&next=%2Finsights')
        })

        it('forwards only params that exist, ignoring missing ones', () => {
            const redirectUrl = '/dashboard'
            const currentSearchParams = { invite_modal: 'true' }
            const forwardedQueryParams = ['invite_modal', 'missing_param']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard?invite_modal=true')
        })

        it('preserves existing query params in redirect URL while adding forwarded ones', () => {
            const redirectUrl = '/dashboard?existing=value'
            const currentSearchParams = { invite_modal: 'true' }
            const forwardedQueryParams = ['invite_modal']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard?existing=value&invite_modal=true')
        })

        it('preserves hash in redirect URL', () => {
            const redirectUrl = '/dashboard#section'
            const currentSearchParams = { invite_modal: 'true' }
            const forwardedQueryParams = ['invite_modal']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard?invite_modal=true#section')
        })

        it('preserves complex hash in redirect URL', () => {
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

        it('handles absolute URLs correctly', () => {
            const redirectUrl = 'https://example.com/dashboard'
            const currentSearchParams = { invite_modal: 'true' }
            const forwardedQueryParams = ['invite_modal']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard?invite_modal=true')
        })

        it('handles empty string values', () => {
            const redirectUrl = '/dashboard'
            const currentSearchParams = { invite_modal: '' }
            const forwardedQueryParams = ['invite_modal']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard?invite_modal=')
        })

        it('handles special characters in param values', () => {
            const redirectUrl = '/dashboard'
            const currentSearchParams = { invite_modal: 'true&false' }
            const forwardedQueryParams = ['invite_modal']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard?invite_modal=true%26false')
        })

        it('does not forward param with falsy values except empty string', () => {
            const redirectUrl = '/dashboard'
            const currentSearchParams = {
                invite_modal: null,
                next: undefined,
                other: false,
                empty: '',
            }
            const forwardedQueryParams = ['invite_modal', 'next', 'other', 'empty']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/dashboard?empty=')
        })

        it('handles complex real-world scenario', () => {
            const redirectUrl = '/insights/new?dashboard=123'
            const currentSearchParams = {
                invite_modal: 'true',
                next: '/original-destination',
                utm_source: 'email',
                other: 'ignored',
            }
            const forwardedQueryParams = ['invite_modal', 'next']

            const result = withForwardedSearchParams(redirectUrl, currentSearchParams, forwardedQueryParams)

            expect(result).toBe('/insights/new?dashboard=123&invite_modal=true&next=%2Foriginal-destination')
        })
    })
})
