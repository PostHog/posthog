import { parseCodexAuthFile } from './codexAuthFile'

describe('parseCodexAuthFile', () => {
    it('reads the tokens from a ChatGPT auth.json', () => {
        const text = JSON.stringify({
            OPENAI_API_KEY: null,
            tokens: {
                id_token: 'fake-id-token',
                access_token: 'fake-access-token',
                refresh_token: 'fake-refresh-token',
                account_id: 'fake-account',
            },
            last_refresh: '2026-01-01T00:00:00Z',
        })

        expect(parseCodexAuthFile(`\n${text}\n`)).toEqual({
            tokens: {
                access_token: 'fake-access-token',
                refresh_token: 'fake-refresh-token',
                id_token: 'fake-id-token',
            },
            error: null,
        })
    })

    it.each([
        ['text that is not JSON', 'codex login', 'does not hold a Codex sign-in'],
        ['an API key login', JSON.stringify({ OPENAI_API_KEY: 'sk-fake', tokens: null }), 'not with an API key'],
        ['a JSON array', '[]', 'not with an API key'],
        ['a file without a refresh token', JSON.stringify({ tokens: { access_token: 'fake' } }), 'missing its tokens'],
    ])('rejects %s', (_name, text, expectedError) => {
        const result = parseCodexAuthFile(text)

        expect(result.tokens).toBeNull()
        expect(result.error).toContain(expectedError)
    })
})
