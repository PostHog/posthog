import { readingGuide, textClauses } from './todayKeyClauses'

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
    ])('splits text into clauses at %s', (_, text, expected) => {
        const clauses = textClauses(text)
        expect(clauses.map((clause) => clause.text)).toEqual(expected)
        expect(clauses.map((clause) => text.slice(clause.start, clause.end))).toEqual(expected)
    })

    test.each([
        [
            'the surest clause for each role asked for',
            ['problem', 'cause'] as const,
            [
                { label: 'problem', probability: 0.8 },
                { label: 'problem', probability: 0.9 },
                { label: 'detail', probability: 0.9 },
                { label: 'cause', probability: 0.85 },
            ],
            [
                ['problem', 'a frozen spinner'],
                ['cause', 'because the cart service drops the session token'],
            ],
        ],
        [
            'nothing for an unsure role',
            ['problem', 'cause'] as const,
            [
                { label: 'problem', probability: 0.6 },
                { label: 'detail', probability: 0.9 },
                { label: 'detail', probability: 0.9 },
                { label: 'cause', probability: 0.7 },
            ],
            [],
        ],
        [
            'only the roles the text asks for',
            ['fix'] as const,
            [
                { label: 'problem', probability: 0.9 },
                { label: 'detail', probability: 0.9 },
                { label: 'detail', probability: 0.9 },
                { label: 'cause', probability: 0.9 },
            ],
            [],
        ],
    ])('marks %s', (_, roles, labelled, expected) => {
        const clauses = textClauses(
            'Shoppers see an empty cart, a frozen spinner, and a blank receipt because the cart service drops the session token.'
        )
        expect(readingGuide(clauses, [...roles], labelled).map((clause) => [clause.role, clause.text])).toEqual(
            expected
        )
    })
})
