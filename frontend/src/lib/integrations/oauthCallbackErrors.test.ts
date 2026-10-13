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

    // Slack sends `access_denied` for an install parked as an admin-approval request too, so the
    // generic "was canceled … approve access" copy is false twice over for that workspace.
    it.each([
        [
            'slack',
            'PostHog was not added to your Slack workspace. Either the install was declined, or your workspace requires an admin to approve new apps and the request is now waiting for one. Once an admin approves it, come back to this page and click "Add to Slack" again.',
        ],
        ['linkedin-ads', 'Authorization was canceled. Please try connecting again and approve access to continue.'],
    ])('describes access_denied for %s', (kind, expected) => {
        expect(describeOAuthCallbackError('access_denied', kind)).toBe(expected)
    })

    it('points Bing Ads users at their Microsoft account when Microsoft rejects the sign-in', () => {
        expect(describeOAuthCallbackError('invalid_client', 'bing-ads')).toContain('Microsoft Advertising account')
    })

    it('falls back to the raw code for unknown errors so support can identify them', () => {
        expect(describeOAuthCallbackError('some_unmapped_code')).toBe('Failed due to "some_unmapped_code".')
    })

    it.each([
        ['no description', undefined, 'Failed due to "invalid_client".'],
        ['an empty description', '  ', 'Failed due to "invalid_client".'],
        [
            'a multi-line description',
            'AADSTS700000: Example sign-in failure.\r\nTrace ID: 00000000-0000',
            'Failed due to "invalid_client". Details from the provider: AADSTS700000: Example sign-in failure.',
        ],
        [
            'a long description',
            'x'.repeat(400),
            `Failed due to "invalid_client". Details from the provider: ${'x'.repeat(300)}…`,
        ],
    ])('appends the first line of the provider description given %s', (_name, description, expected) => {
        expect(describeOAuthCallbackError('invalid_client', undefined, description)).toBe(expected)
    })
})
