import { describeOAuthCallbackError } from './oauthCallbackErrors'

describe('describeOAuthCallbackError', () => {
    // Pins the exact copy that reaches users for every mapped code — the whole point of the module.
    it.each([
        ['access_denied', 'Authorization was canceled. Please try connecting again and approve access to continue.'],
        [
            'user_connector_authorize',
            'Authorization was not completed. Please try connecting again and approve access to continue.',
        ],
        [
            'invalid_scope',
            'The connection was missing required permissions. Please try connecting again and grant all requested access.',
        ],
        ['server_error', 'The provider had a problem completing the connection. Please try again in a moment.'],
        ['temporarily_unavailable', 'The provider is temporarily unavailable. Please try again in a moment.'],
    ])('maps %s to actionable copy', (code, expected) => {
        expect(describeOAuthCallbackError(code)).toBe(expected)
    })

    it('falls back to the raw code for unknown errors so support can identify them', () => {
        expect(describeOAuthCallbackError('some_unmapped_code')).toBe('Failed due to "some_unmapped_code"')
    })
})
