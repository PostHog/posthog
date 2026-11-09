import { HOG_FUNCTION_TEMPLATES } from '../templates'
import { CredentialAuthDeclaration, INTEGRATION_AUTH, ResolvedCredential, applyCredential } from './credential-auth'

describe('credential auth', () => {
    const credential = (declaration: CredentialAuthDeclaration, username?: string): ResolvedCredential => ({
        inputKey: 'api_key',
        declaration,
        origins: ['https://api.example.com'],
        secret: 'sk_secret',
        username,
    })

    const request = {
        url: 'https://api.example.com/send?key=from_code&page=1',
        headers: { 'x-api-key': 'from_code', 'Content-Type': 'application/json' },
        body: '{"auth":{"token":"from_code"},"text":"hello"}',
    }

    it.each([
        [
            'a header with a prefix, replacing the one the code set',
            credential({ scheme: 'header', name: 'X-Api-Key', prefix: 'Token ' }),
            { headers: { 'Content-Type': 'application/json', 'X-Api-Key': 'Token sk_secret' } },
        ],
        [
            'basic auth with the username input',
            credential({ scheme: 'basic', username_input: 'user' }, 'account'),
            {
                headers: {
                    ...request.headers,
                    Authorization: `Basic ${Buffer.from('account:sk_secret').toString('base64')}`,
                },
            },
        ],
        [
            'a query parameter, replacing the one the code set',
            credential({ scheme: 'query', name: 'key', opt_in: true }),
            { url: 'https://api.example.com/send?key=sk_secret&page=1' },
        ],
        [
            'a body path, replacing the value the code set',
            credential({ scheme: 'body', path: 'auth.token', opt_in: true }),
            { body: '{"auth":{"token":"sk_secret"},"text":"hello"}' },
        ],
    ])('applies %s', (_name, resolved, expected) => {
        expect(applyCredential(request, resolved)).toEqual({ ok: true, request: { ...request, ...expected } })
    })

    it('refuses a body path when the body is not a JSON object', () => {
        const outcome = applyCredential({ ...request, body: '["list"]' }, credential({ scheme: 'body', path: 'token' }))

        expect(outcome.ok).toBe(false)
    })

    // A template whose connection kind the worker does not know fails every send, so this catches it before release.
    it('knows the placement of every connection kind a template applies as a credential', () => {
        const declared = HOG_FUNCTION_TEMPLATES.flatMap((template) =>
            (template.inputs_schema ?? [])
                .filter((schema) => schema.type === 'integration' && schema.auth)
                .map((schema) => ({ template: template.id, kind: schema.integration, auth: schema.auth }))
        )

        expect(declared.length).toBeGreaterThan(0)
        for (const { template, kind, auth } of declared) {
            expect({ template, auth: INTEGRATION_AUTH[kind ?? '']?.declaration }).toEqual({ template, auth })
        }
    })
})
