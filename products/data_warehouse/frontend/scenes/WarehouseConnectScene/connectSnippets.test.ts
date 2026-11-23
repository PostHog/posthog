import { buildConnectSnippets } from './connectSnippets'

describe('buildConnectSnippets', () => {
    const connection = { host: 'acme.us.postwh.com', port: 443, catalog: 'acme_lake', username: 'acme_root' }

    it.each([
        ['analytics', 'acme_root'],
        [null, 'acme_reader'],
    ])('fills the live connection and never a secret or JDBC URL, schema %s, login %s', (schema, username) => {
        const snippets = buildConnectSnippets({ ...connection, username }, schema)

        expect(snippets.map((snippet) => snippet.key)).toEqual(['trino_cli', 'python', 'dbt', 'metabase', 'hex'])
        for (const snippet of snippets) {
            expect(snippet.code).toContain('acme.us.postwh.com')
            expect(snippet.code).toContain('acme_lake')
            expect(snippet.code).toContain(username)
            expect(snippet.code).not.toContain('<your credential')
            expect(snippet.code).not.toContain('jdbc:')
        }
        expect(snippets.every((snippet) => snippet.code.includes('analytics') === (schema !== null))).toBe(true)
    })
})
