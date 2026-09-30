import { accountsDropdownEmptyMessage, reconnectReturnUrl } from './IntegrationAccountSelector'

describe('IntegrationAccountSelector', () => {
    // A failed listing request leaves the same empty list as a connection that reaches no accounts,
    // and the picker used to report both as the second one.
    it('separates a failed account listing from a connection with no accounts', () => {
        expect(accountsDropdownEmptyMessage('Reconnect your Google account.')).not.toEqual(
            accountsDropdownEmptyMessage(null)
        )
        expect(accountsDropdownEmptyMessage(null)).toContain('No accounts accessible')
    })

    it.each([
        [
            '/project/1/data-warehouse/new-source',
            '?kind=googlesearchconsole',
            '/project/1/data-warehouse/new-source?kind=googlesearchconsole',
        ],
        [
            '/project/1/data-warehouse/new-source',
            '?kind=googlesearchconsole&integration_id=5&integration_error=access_denied',
            '/project/1/data-warehouse/new-source?kind=googlesearchconsole',
        ],
        ['/project/1/data-warehouse/sources/abc', '', '/project/1/data-warehouse/sources/abc'],
    ])('returns a reconnect from %s%s to the same wizard step', (pathname, search, expected) => {
        expect(reconnectReturnUrl(pathname, search)).toEqual(expected)
    })
})
