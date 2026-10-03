import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import { signalDetail, signalHeadline, signalMeta } from './todaySignalText'
import { signal } from './todayTestFixtures'

describe('todaySignalText', () => {
    test.each([
        [
            'an error tracking issue',
            'New error tracking issue created - this particular exception was observed for the first time:\nValueError: `coupon_code`\n\n```\nstack\n```',
            'ValueError: coupon_code',
        ],
        [
            'a support ticket',
            'C: Two weekly invoices show a blank total for annual plans\\. They bill in euros.',
            'Two weekly invoices show a blank total for annual plans.',
        ],
        [
            'long scout prose',
            'The invoice export leaves out the tax column for archived plans. A nightly sync adds it back later.',
            'The invoice export leaves out the tax column for archived plans.',
        ],
        [
            'a github issue cited with a bare link',
            'GitHub issue #4521 (https://github.com/example/shop/issues/4521) reports that `Card was declined. Use another.` shows for `card_error`. It has no PR.',
            'GitHub issue #4521 reports that “Card was declined. Use another.” shows for card_error.',
        ],
        [
            'a long sentence, cut at its last clause',
            'Pressing Apply on the shipping rules settings screen does not keep the new rates, which means every edit to the rates is dropped and the merchant has to write to the help desk about it before the next billing run.',
            'Pressing Apply on the shipping rules settings screen does not keep the new rates, which means every edit to the rates is dropped and the merchant has…',
        ],
        [
            'a long sentence, never cut inside a quotation',
            'In the #shop-support thread about failed payments, one merchant reported that checkouts on the mobile app fail about a third of the time with “Gateway did not answer in time” errors.',
            'In the #shop-support thread about failed payments, one merchant reported that checkouts on the mobile app fail about a third of the time…',
        ],
        [
            'a pganalyze issue',
            '[info] orders-db — #42\nQuery #42 takes 95 ms on average (12345 calls in last 24h)',
            'Query #42 takes 95 ms on average (12,345 calls in last 24h)',
        ],
        [
            'an alert investigation',
            "Anomaly investigation for alert 'Orders dropped' on Orders (verdict: true positive).\nInsight: AB12 / id 1.\nPaid orders fell to 12 in the 09:00 hour on 2026-08-03. The detector fired before.",
            'Paid orders fell to 12 in the 09:00 hour on 3 Aug.',
        ],
        [
            'a scout finding that ends in a thread link',
            'A reviewer said the banner is too loud. Slack reply: https://example.slack.com/archives/C1/p2',
            'A reviewer said the banner is too loud.',
        ],
    ])('writes a headline for %s', (_, content, expected) => {
        expect(signalHeadline(signal({ content }))).toEqual(expected)
    })

    test.each([
        [
            'a support ticket',
            signal({
                source_product: 'conversations',
                extra: { ticket_number: 1042, priority: 'low' } as unknown as SignalNodeApi['extra'],
            }),
            'Ticket #1042',
        ],
        [
            'a github issue',
            signal({
                source_product: 'github',
                source_type: 'issue',
                extra: { number: 7, author_login: 'ada', state: 'open' } as unknown as SignalNodeApi['extra'],
            }),
            'Issue #7',
        ],
        ['a scout finding on a file', signal({ source_id: 'example/web:src/checkout/Address.tsx' }), 'Address.tsx'],
        [
            'a recording',
            signal({
                source_product: 'replay_vision',
                extra: { scanner_name: 'Checkout friction' } as unknown as SignalNodeApi['extra'],
            }),
            '',
        ],
    ])('names only the identifier of %s under its headline', (_, input, expected) => {
        expect(signalMeta(input)).toEqual(expected)
    })

    test.each([
        [
            'a pganalyze issue, without its header line',
            signal({
                source_product: 'pganalyze',
                source_type: 'issue',
                content: '[info] orders-db — #42\nQuery #42 takes 95 ms on average (12345 calls in last 24h)',
                extra: { server_name: 'orders-db', severity: 'info' } as SignalNodeApi['extra'],
            }),
            {
                lead: 'Query #42 takes 95 ms on average (12,345 calls in last 24h)',
                rest: '',
                facts: ['orders-db', 'info severity'],
            },
        ],
        [
            'a scout finding that cites a Slack thread, without the sentence that only points at it',
            signal({
                content:
                    'The August 12 #shop-support discussion counted 2,316 merchants using saved carts over 30 days. Most were on the annual plan. The thread is available at https://example.slack.com/archives/C1/p2.',
                extra: { skill_name: 'signals-scout-shop-support' } as SignalNodeApi['extra'],
            }),
            {
                lead: 'The August 12 #shop-support discussion counted 2,316 merchants using saved carts over 30 days.',
                rest: 'Most were on the annual plan.',
                facts: [],
            },
        ],
        [
            'a scout finding, split into its lead and the rest',
            signal({
                content:
                    'The 14-message thread records a recurring gap in the order history page. The discussion proposes a date filter.',
                extra: { skill_name: 'signals-scout-shop-support' } as SignalNodeApi['extra'],
            }),
            {
                lead: 'The 14-message thread records a recurring gap in the order history page.',
                rest: 'The discussion proposes a date filter.',
                facts: [],
            },
        ],
    ])('opens %s', (_, item, expected) => {
        expect(signalDetail(item)).toEqual(expected)
    })
})
