import { describeOAuthCallbackError } from './oauthCallbackErrors'

describe('describeOAuthCallbackError', () => {
    it('maps known provider error codes to actionable copy', () => {
        expect(describeOAuthCallbackError('access_denied')).toContain('Authorization was canceled')
        expect(describeOAuthCallbackError('user_connector_authorize')).toContain('Authorization was not completed')
    })

    it('falls back to the raw code for unknown errors so support can identify them', () => {
        expect(describeOAuthCallbackError('some_unmapped_code')).toBe('Failed due to "some_unmapped_code"')
    })
})
