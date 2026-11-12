import type { IntegrationAccountApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { accountToAutoFill } from './CredentialAccountSelector'

const account = (value: string): IntegrationAccountApi => ({
    value,
    display_name: `Account ${value}`,
    is_primary: false,
    badges: [],
    group: null,
    secondary_text: null,
})

describe('accountToAutoFill', () => {
    // Leaving the account field empty fails the connect step, even when the credentials can read
    // only one account, so the picker fills that one in.
    test.each([
        ['one account and an empty field', [account('111')], null, undefined, '111'],
        ['one account and a blank string', [account('111')], null, '', '111'],
        ['one account and only whitespace', [account('111')], null, '   ', '111'],
        ['one account and a value already set', [account('111')], null, '222', null],
        ['several accounts to choose from', [account('111'), account('222')], null, undefined, null],
        ['no accounts', [], null, undefined, null],
        ['a failed listing', [account('111')], 'These credentials were rejected.', undefined, null],
    ])('%s', (_, accounts, accountsError, currentValue, expected) => {
        expect(accountToAutoFill(accounts, accountsError, currentValue)).toEqual(expected)
    })
})
