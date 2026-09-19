import { resolveBearerToken } from './bearer-token'

describe('resolveBearerToken', () => {
    const inputs_schema = [{ key: 'api_key', type: 'string' as const, secret: true }]

    it('uses the encrypted value before a stale plaintext value', () => {
        expect(
            resolveBearerToken('https://example.com', 'api_key', {
                inputs_schema,
                inputs: { api_key: { value: 'old-fake-key' } },
                encrypted_inputs: { api_key: { value: 'new-fake-key' } },
            })
        ).toEqual({ ok: true, token: 'new-fake-key' })
    })

    it('resolves a workflow key from its decrypted action inputs', () => {
        expect(
            resolveBearerToken('https://example.com', 'api_key', {
                inputs_schema,
                inputs: { api_key: { value: 'fake-workflow-key' } },
            })
        ).toEqual({ ok: true, token: 'fake-workflow-key' })
    })

    it.each([
        ['http://example.com', 'fake-key', true],
        ['invalid-url', 'fake-key', true],
        ['https://example.com', '', true],
        ['https://example.com', '  ', true],
        ['https://example.com', 'fake\r\nkey', true],
        ['https://example.com', 'fake-key', false],
        ['https://example.com', null, true],
    ])('rejects an unsafe request or invalid secret (%s, %s, %s)', (url, token, secret) => {
        expect(
            resolveBearerToken(url, 'api_key', {
                inputs_schema: [{ ...inputs_schema[0], secret }],
                inputs: { api_key: { value: token } },
            })
        ).toMatchObject({ ok: false })
    })
})
