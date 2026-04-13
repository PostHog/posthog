// Regression test: the @posthog/hogql-parser package works in Jest without mocks
import createHogQLParser from '@posthog/hogql-parser'

describe('@posthog/hogql-parser', () => {
    it('exports a factory function', () => {
        expect(typeof createHogQLParser).toBe('function')
    })

    it('factory resolves to a parser with parseSelect', async () => {
        const parser = await createHogQLParser()
        expect(typeof parser.parseSelect).toBe('function')
    })

    it('parses a simple SELECT statement', async () => {
        const parser = await createHogQLParser()
        const result = JSON.parse(parser.parseSelect('SELECT 1'))
        expect(result.node).toBe('SelectQuery')
    })
})
