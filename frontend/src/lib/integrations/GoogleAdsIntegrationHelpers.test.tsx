import { normalizeCustomerIdValue } from './GoogleAdsIntegrationHelpers'

describe('GoogleAdsIntegrationHelpers', () => {
    // The destination reads the stored value as `<customer id>/<login customer id>`, so a typed value
    // without the second half sends an empty login-customer-id header and every upload fails.
    test.each([
        ['a picked option', '1234567890/6501924158', '1234567890/6501924158'],
        ['a typed customer id', '1234567890', '1234567890/1234567890'],
        ['a typed customer id with dashes', '123-456-7890', '1234567890/1234567890'],
        ['a typed pair with dashes', '123-456-7890/650-192-4158', '1234567890/6501924158'],
        ['a value with no digits', 'my account', null],
    ])('normalizes %s', (_name, value, expected) => {
        expect(normalizeCustomerIdValue(value)).toEqual(expected)
    })
})
