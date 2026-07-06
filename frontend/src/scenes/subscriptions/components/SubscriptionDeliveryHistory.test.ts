import { stripDeliveryHistoryPointer } from './SubscriptionDeliveryHistory'

describe('stripDeliveryHistoryPointer', () => {
    it.each([
        // The degraded notice loses only its "check the delivery history" pointer; the warning + body stay.
        [
            "> ⚠️ This report could not be generated — all 2 queries the assistant wrote failed to run. Check the subscription's delivery history in PostHog for the generated queries and errors.\n\n## Report\n\nbody",
            '> ⚠️ This report could not be generated — all 2 queries the assistant wrote failed to run.\n\n## Report\n\nbody',
        ],
        // A report without the pointer is returned unchanged (no over-stripping).
        ['## Weekly report\n\nAll good.', '## Weekly report\n\nAll good.'],
    ])('strips the in-app-redundant delivery-history pointer, leaving everything else', (input, expected) => {
        expect(stripDeliveryHistoryPointer(input)).toBe(expected)
    })
})
