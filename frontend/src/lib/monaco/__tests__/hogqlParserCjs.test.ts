// Regression test: the CJS entrypoint must work without import.meta.url or dynamic import()

import path from 'path'

// Use the local dist build directly to test the CJS wrapper
// eslint-disable-next-line @typescript-eslint/no-require-imports
const createHogQLParser = require(
    path.resolve(__dirname, '..', '..', '..', '..', '..', 'common', 'hogql_parser', 'dist', 'index.cjs')
)

describe('@posthog/hogql-parser CJS entrypoint', () => {
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
