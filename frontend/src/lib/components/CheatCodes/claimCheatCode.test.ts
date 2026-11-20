/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { claimCheatCode } from './claimCheatCode'

describe('claimCheatCode', () => {
    beforeEach(() => {
        initKeaTests()
        jest.spyOn(window.HTMLMediaElement.prototype, 'play').mockResolvedValue()
    })

    it.each([
        ['Customer must have an active card on file before claiming this coupon.', 'needs_billing'],
        ['Customer must have an active subscription before claiming this coupon.', 'needs_billing'],
        ['Customer must have an active payment method before claiming this coupon.', 'needs_billing'],
        ['Customer has already claimed a coupon from this campaign.', 'already_claimed'],
        ['This campaign is paused and coupons cannot be claimed', 'failed'],
    ])('reads the billing error %p as %p', async (detail, expected) => {
        useMocks({ post: { '/api/billing/coupons/claim': () => [400, { detail }] } })

        expect(await claimCheatCode('hesoyam')).toEqual(expected)
    })
})
