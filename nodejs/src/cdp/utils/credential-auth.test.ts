import { HOG_FUNCTION_TEMPLATES } from '../templates'
import {
    CredentialAuthDeclaration,
    INTEGRATION_AUTH,
    ResolvedCredential,
    applyCredential,
    publicIntegrationConfig,
    requestOrigin,
    routedOrigins,
} from './credential-auth'
import ORIGIN_CASES from './credential-origin-cases.json'

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
            'basic auth with the username field',
            credential({ scheme: 'basic', username_field: 'user' }, 'account'),
            {
                headers: {
                    ...request.headers,
                    Authorization: `Basic ${Buffer.from('account:sk_secret').toString('base64')}`,
                },
            },
        ],
        [
            'a query parameter, replacing the one the code set',
            credential({ scheme: 'query', name: 'key' }),
            { url: 'https://api.example.com/send?key=sk_secret&page=1' },
        ],
        [
            'a body path, replacing the value the code set',
            credential({ scheme: 'body', path: 'auth.token' }),
            { body: '{"auth":{"token":"sk_secret"},"text":"hello"}' },
        ],
    ])('applies %s', (_name, resolved, expected) => {
        expect(applyCredential(request, resolved)).toEqual({ ok: true, request: { ...request, ...expected } })
    })

    it.each([
        ['a body that is not a JSON object', '["list"]', 'token'],
        ['__proto__ in the path', request.body, '__proto__.token'],
        ['constructor in the path', request.body, 'constructor.prototype.token'],
        ['prototype in the path', request.body, 'auth.prototype'],
    ])('refuses a body path with %s', (_name, body, path) => {
        const outcome = applyCredential({ ...request, body }, credential({ scheme: 'body', path }))

        expect(outcome.ok).toBe(false)
        expect(({} as Record<string, unknown>).token).toBeUndefined()
    })

    it('keeps tokens and the Slack webhook URL out of the config code sees', () => {
        const config = {
            team: { id: 'T1', name: 'Example' },
            access_token: 'xoxb-1',
            authed_user: { id: 'U1', access_token: 'xoxp-1' },
            incoming_webhook: { channel: '#alerts', url: 'https://hooks.slack.com/services/T1/B1/x' },
        }

        expect(publicIntegrationConfig(config, { refresh_token: 'r' })).toEqual({ team: config.team })
    })

    it.each(ORIGIN_CASES.url_origins)('reads $url as the origin $origin', ({ url, origin }) => {
        expect(requestOrigin(url)).toBe(origin)
    })

    it.each(ORIGIN_CASES.routed_origins)('routes $url with $headers to $origins', ({ url, headers, origins }) => {
        expect(routedOrigins({ url, headers: headers as Record<string, string>, body: undefined })).toEqual(origins)
    })

    it('knows the scheme of every connection kind a template applies as a credential', () => {
        const declared = HOG_FUNCTION_TEMPLATES.flatMap((template) =>
            (template.inputs_schema ?? [])
                .filter((schema) => schema.type === 'integration' && schema.auth)
                .map((schema) => ({ template: template.id, kind: schema.integration, auth: schema.auth }))
        )

        expect(declared.length).toBeGreaterThan(0)
        for (const { template, kind, auth } of declared) {
            expect({ template, scheme: INTEGRATION_AUTH[kind ?? '']?.declaration.scheme }).toEqual({
                template,
                scheme: auth?.scheme,
            })
        }
    })
})
