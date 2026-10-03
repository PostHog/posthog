import type { JevClient, JevPick } from './todayJev'
import { findKeyClauses, textClauses } from './todayKeyClauses'

const CART_TEXT =
    'Shoppers see an empty cart, a frozen spinner, and a blank receipt because the cart service drops the session token.'
const FIX_TEXT = 'Keep the token in a cookie so the cart survives the switch.'
const CART_EXPLAINED = 'The cart page renders before the session loads and shows zero items.'
const SPINNER_EXPLAINED = 'The spinner waits on a price request that never returns.'
const CAUSE_EXPLAINED = 'The service drops the token when a shopper moves from the app to the browser.'
const FIX_EXPLAINED = 'A cookie keeps the token across that move for one extra header.'
const SUMMARY = [CART_TEXT, FIX_TEXT, CART_EXPLAINED, SPINNER_EXPLAINED, CAUSE_EXPLAINED, FIX_EXPLAINED].join('\n\n')

const EMPTY_CART = 'Shoppers see an empty cart'
const FROZEN_SPINNER = 'a frozen spinner'
const CAUSE = 'because the cart service drops the session token'
const FIX = 'Keep the token in a cookie'

function fakeJev(texts: string[], roles: Record<string, JevPick>, explanations: Record<string, string>): JevClient {
    const markedPart = (item: string): string => {
        const part = texts.reduce((rest, text) => rest.replace(text, ''), item)
        return Object.keys(roles).find((clause) => part.includes(clause)) ?? ''
    }
    const explains = (item: string): boolean =>
        Object.entries(explanations).some(([clause, sentence]) => item.includes(clause) && item.includes(sentence))
    return {
        choice: async (items) => items.map((item) => roles[markedPart(item)] ?? null),
        yes: async (items) => items.map((item) => (explains(item) ? 0.9 : 0.1)),
    }
}

function shown(found: Record<string, { text: string; expansion: string[] }[]>): Record<string, [string, string[]][]> {
    return Object.fromEntries(
        Object.entries(found).map(([text, clauses]) => [
            text,
            clauses.map((clause): [string, string[]] => [clause.text, clause.expansion]),
        ])
    )
}

describe('todayKeyClauses', () => {
    test.each([
        [
            'punctuation and a word that opens a clause',
            'Shoppers on the mobile app see an empty cart, a frozen spinner, and a blank receipt because the cart service drops the session token.',
            [
                'Shoppers on the mobile app see an empty cart',
                'a frozen spinner',
                'and a blank receipt',
                'because the cart service drops the session token',
            ],
        ],
        [
            'file names and an uppercase OR kept whole',
            'The filter in orders_view.ts joins carts across an OR, so each query scans every row.',
            ['The filter in orders_view.ts joins carts across an OR', 'so each query scans every row'],
        ],
        [
            'a dash between clauses but not inside a number range',
            'Checkout fails for 120–150 shoppers a week – the coupon step drops their cart.',
            ['Checkout fails for 120–150 shoppers a week', 'the coupon step drops their cart'],
        ],
    ])('splits text into clauses at %s', (_, text, expected) => {
        expect(textClauses(text).map((clause) => clause.text)).toEqual(expected)
    })

    test.each([
        [
            'the surest clause for each role',
            {
                [EMPTY_CART]: { label: 'problem', probability: 0.8 },
                [FROZEN_SPINNER]: { label: 'problem', probability: 0.9 },
                [CAUSE]: { label: 'cause', probability: 0.85 },
            },
            { [EMPTY_CART]: CART_EXPLAINED, [FROZEN_SPINNER]: SPINNER_EXPLAINED, [CAUSE]: CAUSE_EXPLAINED },
            [
                [FROZEN_SPINNER, [SPINNER_EXPLAINED]],
                [CAUSE, [CAUSE_EXPLAINED]],
            ],
        ],
        [
            'only a clause the report explains',
            {
                [FROZEN_SPINNER]: { label: 'problem', probability: 0.95 },
                [CAUSE]: { label: 'cause', probability: 0.8 },
            },
            { [CAUSE]: CAUSE_EXPLAINED },
            [[CAUSE, [CAUSE_EXPLAINED]]],
        ],
        [
            'nothing for an unsure role',
            {
                [FROZEN_SPINNER]: { label: 'problem', probability: 0.7 },
                [CAUSE]: { label: 'cause', probability: 0.7 },
            },
            { [FROZEN_SPINNER]: SPINNER_EXPLAINED, [CAUSE]: CAUSE_EXPLAINED },
            [],
        ],
    ])('shows %s', async (_, roles, explanations, expected) => {
        const found = await findKeyClauses(
            [{ text: CART_TEXT, roles: ['problem', 'cause'] }],
            SUMMARY,
            fakeJev([CART_TEXT], roles, explanations)
        )
        expect(shown(found)).toEqual({ [CART_TEXT]: expected })
    })

    test('gives each text its own clauses, and at most two across all texts', async () => {
        const found = await findKeyClauses(
            [
                { text: CART_TEXT, roles: ['problem', 'cause'] },
                { text: FIX_TEXT, roles: ['fix'] },
            ],
            SUMMARY,
            fakeJev(
                [CART_TEXT, FIX_TEXT],
                {
                    [FROZEN_SPINNER]: { label: 'problem', probability: 0.95 },
                    [CAUSE]: { label: 'cause', probability: 0.8 },
                    [FIX]: { label: 'fix', probability: 0.9 },
                },
                { [FROZEN_SPINNER]: SPINNER_EXPLAINED, [CAUSE]: CAUSE_EXPLAINED, [FIX]: FIX_EXPLAINED }
            )
        )
        expect(shown(found)).toEqual({
            [CART_TEXT]: [[FROZEN_SPINNER, [SPINNER_EXPLAINED]]],
            [FIX_TEXT]: [[FIX, [FIX_EXPLAINED]]],
        })
    })
})
