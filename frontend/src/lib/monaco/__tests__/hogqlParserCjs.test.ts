// Regression test: the @posthog/hogql-parser package works in Jest without mocks
import fs from 'fs'
import path from 'path'

import createHogQLParser from '@posthog/hogql-parser'

// The app's CSP has no 'unsafe-eval', so the published glue must be linked with
// DYNAMIC_EXECUTION=0. Emscripten does not fail the build without it: the default embind emits a
// `new Function` invoker, and with the flag a binding that still needs eval becomes a runtime
// abort. Both leave a fixed string in the output, so the check runs on the pinned package.
const GLUE_FILES = ['hogql_parser_wasm_browser.js', 'hogql_parser_wasm.js', 'hogql_parser_wasm.cjs']

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

    it.each(GLUE_FILES)('%s is built without dynamic execution', (file) => {
        const distDir = path.dirname(require.resolve('@posthog/hogql-parser'))
        const glue = fs.readFileSync(path.join(distDir, file), 'utf8')
        expect(glue).not.toContain('new Function(')
        expect(glue).not.toContain('DYNAMIC_EXECUTION=0 was set')
    })
})
