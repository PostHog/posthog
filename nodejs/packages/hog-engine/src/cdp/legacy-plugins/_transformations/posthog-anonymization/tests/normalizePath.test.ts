import { normalizePath } from '../src/normalizePath'

describe('normalizePath', () => {
    it('removes IDs from the URL Hash', () => {
        const actual = normalizePath('https://example.com/example.html#accounts/ASD123/cards')

        expect(actual).toMatchInlineSnapshot(`"https://example.com/example.html#accounts/:id/cards"`)
    })

    it('removes get parameters from URL Hash', () => {
        const actual = normalizePath('https://example.com/example.html#accounts/cards?test=foo')

        expect(actual).toMatchInlineSnapshot(`"https://example.com/example.html#accounts/cards"`)
    })

    it('removes IDs and get parameters from bulk transfer url hash', () => {
        const actual = normalizePath(
            'https://example.com/example.html#/path/to/THE_THING/830baf73-2f70-4194-b18e-8900c0281f49?backUrl=foobar'
        )

        expect(actual).toMatchInlineSnapshot(`"https://example.com/example.html#/path/to/:id/:id"`)
    })

    it('keeps the domain intact when it contains numbers', () => {
        const actual = normalizePath(
            'https://example.com/?at=c#/currentAccount/830baf73-2f70-4194-b18e-8900c0281f49/transactions'
        )

        expect(actual).toMatchInlineSnapshot(`"https://example.com/#/currentAccount/:id/transactions"`)
    })

    it('removes the query param, but keeps the path in the hash for normalization', () => {
        const actual = normalizePath('https://example.com/index.html?at=c&lang=en#/overview')

        expect(actual).toMatchInlineSnapshot(`"https://example.com/index.html#/overview"`)
    })

    it('normalizes encoded URIs', () => {
        const actual = normalizePath(
            'https%3A%2F%2Fexample.com%2F%3Fat%3Dc%23%2FcurrentAccount%2F830baf73-2f70-4194-b18e-8900c0281f49%2Ftransactions'
        )

        expect(actual).toMatchInlineSnapshot(`"https://example.com/#/currentAccount/:id/transactions"`)
    })
})
