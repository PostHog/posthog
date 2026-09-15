import { accountsDropdownEmptyMessage } from './IntegrationAccountSelector'

describe('IntegrationAccountSelector', () => {
    // A failed listing request leaves the same empty list as a connection that reaches no accounts,
    // and the picker used to report both as the second one.
    it('separates a failed account listing from a connection with no accounts', () => {
        expect(accountsDropdownEmptyMessage('Reconnect your Google account.')).not.toEqual(
            accountsDropdownEmptyMessage(null)
        )
        expect(accountsDropdownEmptyMessage(null)).toContain('No accounts accessible')
    })
})
